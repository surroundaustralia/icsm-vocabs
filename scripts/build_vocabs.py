"""Build the published vocabularies in vocabs/ from the CSV sources in source/.

Pipeline:

1. Uplift: every CSV matched by the domain configuration (.ogc/catalog.ttl) is converted
   to RDF with ogc.na.ingest_json, using source/vocabs-uplift.yml. This runs in a temporary
   copy of the sources so nothing is generated alongside the CSVs.
2. Build: each uplifted vocabulary is merged with its ConceptScheme metadata (creator,
   publisher, dates, status, definition...) and written as a draft to source/ttl-drafts/.
   Concepts always come from the CSV. Scheme metadata comes from, in order of preference:
     - a sidecar file next to the CSV named <name>.meta.ttl, or
     - the existing published file vocabs/<same path>.ttl.
   Top concepts are computed and missing concept definitions are given an empty
   placeholder, matching the existing published vocabularies.
3. Validate: each draft is validated as Prez would load it - it must be listed in
   manifest.ttl and conform to the validator declared there (dct:conformsTo), with the
   manifest's labels as background. If all drafts pass, the whole manifest is then
   validated with prezmanifest against a staged copy of the repository that includes the
   drafts.
4. Publish: if everything passed, drafts are moved into vocabs/ and source/ttl-drafts/ is
   deleted. Otherwise the drafts are left in source/ttl-drafts/ together with
   validation-report.md, and the script exits with status 1.

Run from anywhere:  python scripts/build_vocabs.py --help
"""

import argparse
import csv
import datetime
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import kurra.shacl
from prezmanifest.utils import get_background_graph
from prezmanifest.validator import ManifestValidationError
from prezmanifest.validator import validate as validate_manifest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import DCTERMS, PROF, RDF, SDO, SKOS, XSD

REPO_DIR = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_DIR / "source"
VOCABS_DIR = REPO_DIR / "vocabs"
DRAFTS_DIR = SOURCE_DIR / "ttl-drafts"
REPORT_FILE = DRAFTS_DIR / "validation-report.md"
MANIFEST_FILE = REPO_DIR / "manifest.ttl"
UNDEFINED_SCHEME = "https://icsm.gov.au/csdm/vocabs/notdefined"
MRR_RESOURCE_DATA = URIRef("https://prez.dev/ManifestResourceRoles/ResourceData")
# maximum lines of SHACL output shown per vocabulary in the report
MAX_RESULT_LINES = 150


@dataclass
class Vocab:
    csv: Path  # relative to SOURCE_DIR
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    concept_count: int = 0
    unchanged: bool = False

    @property
    def rel_ttl(self) -> Path:
        return self.csv.with_suffix(".ttl")

    @property
    def draft(self) -> Path:
        return DRAFTS_DIR / self.rel_ttl

    @property
    def published(self) -> Path:
        return VOCABS_DIR / self.rel_ttl

    @property
    def sidecar(self) -> Path:
        return SOURCE_DIR / self.csv.with_suffix(".meta.ttl")

    @property
    def manifest_path(self) -> str:
        return (Path("vocabs") / self.rel_ttl).as_posix()


def log(msg: str = ""):
    print(msg, flush=True)


# --------------------------------------------------------------------------------------
# 1. Uplift
# --------------------------------------------------------------------------------------


def uplift(work_dir: Path, file_filter: str | None) -> tuple[dict[Path, Path], str]:
    """Runs ogc.na.ingest_json over a copy of the sources in work_dir.

    Returns a mapping of CSV path (relative to source/) to uplifted TTL, and the tool output."""
    shutil.copytree(REPO_DIR / ".ogc", work_dir / ".ogc")
    shutil.copytree(
        SOURCE_DIR,
        work_dir / "source",
        ignore=shutil.ignore_patterns("ttl-drafts", "*.ttl", "*.jsonld"),
    )

    cmd = [
        sys.executable, "-m", "ogc.na.ingest_json",
        "--batch", "--all", "--skip-on-missing-context", "--ttl", "--no-provenance",
        "--work-dir", ".", "--domain-config", ".ogc/catalog.ttl",
    ]
    if file_filter:
        cmd += ["--file-filter", file_filter]
    proc = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, encoding="utf-8")
    output = proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"ogc.na.ingest_json failed (exit {proc.returncode}):\n{output}")

    work_source = work_dir / "source"
    results = {}
    for csv in sorted(work_source.rglob("*.csv")):
        rel = csv.relative_to(work_source)
        if file_filter and not re.search(file_filter, str(csv)):
            continue
        results[rel] = csv.with_suffix(".ttl")
    return results, output


# --------------------------------------------------------------------------------------
# 2. Build
# --------------------------------------------------------------------------------------


def check_csv(vocab: Vocab):
    """Flags rows that would mint the same concept IRI with different labels.

    Mirrors the IRI rule in source/vocabs-uplift.yml: notation (or preflabel when there is
    no notation), trimmed, with characters other than letters, digits, _ and - replaced by -.
    """
    def value(row, key):
        v = (row.get(key) or "").strip()
        return None if v in ("", "-") else v

    rows: dict[str, list[tuple[int, str]]] = {}
    with open(SOURCE_DIR / vocab.csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [k.strip().lower() for k in reader.fieldnames or []]
        for row in reader:
            key = value(row, "notation") or value(row, "preflabel")
            if key:
                local_id = re.sub(r"[^a-zA-Z0-9_-]", "-", key)
                rows.setdefault(local_id, []).append((reader.line_num, value(row, "preflabel") or key))

    for local_id, entries in rows.items():
        if len({label for _, label in entries}) > 1:
            described = ", ".join(f"{n} ({label!r})" for n, label in entries)
            vocab.errors.append(
                f"CSV lines {described} all produce the concept id `{local_id}` - "
                "each concept needs a unique notation"
            )


def _bnode_closure(g: Graph, roots: set) -> set:
    """All blank nodes reachable from roots."""
    seen, todo = set(), list(roots)
    while todo:
        for o in g.objects(todo.pop(), None):
            if isinstance(o, BNode) and o not in seen:
                seen.add(o)
                todo.append(o)
    return seen


def _label(g: Graph, iri) -> str:
    return str(g.value(iri, SKOS.prefLabel) or iri)


def build(vocab: Vocab, generated: Graph) -> Graph | None:
    """Merges an uplifted vocabulary with its ConceptScheme metadata."""
    schemes = set(generated.subjects(RDF.type, SKOS.ConceptScheme))
    if len(schemes) != 1:
        vocab.errors.append(f"Uplift produced {len(schemes)} ConceptSchemes, expected exactly 1")
        return None
    scheme = schemes.pop()
    if str(scheme) == UNDEFINED_SCHEME:
        vocab.errors.append(
            f"`{vocab.csv.name}` has no entry in the csMapping of source/vocabs-uplift.yml - "
            "add its ConceptScheme IRI, label and concept type there"
        )
        return None

    concepts = set(generated.subjects(RDF.type, SKOS.Concept))
    vocab.concept_count = len(concepts)
    if not concepts:
        vocab.errors.append("Uplift produced no concepts - is the CSV empty or missing a preflabel/notation column?")

    if vocab.sidecar.is_file():
        meta_source = vocab.sidecar
    elif vocab.published.is_file():
        meta_source = vocab.published
    else:
        meta_source = None
        vocab.errors.append(
            f"No ConceptScheme metadata found. Create `source/{vocab.csv.with_suffix('.meta.ttl').as_posix()}` "
            "with the scheme's definition, creator, publisher, dates and status"
        )

    out = Graph()
    meta = Graph()
    if meta_source is not None:
        try:
            meta.parse(meta_source)
        except Exception as e:
            vocab.errors.append(f"Could not parse metadata file `{meta_source.relative_to(REPO_DIR)}`: {e}")
            return None
        if scheme not in set(meta.subjects(RDF.type, SKOS.ConceptScheme)):
            vocab.errors.append(
                f"Metadata file `{meta_source.relative_to(REPO_DIR).as_posix()}` does not describe the "
                f"ConceptScheme <{scheme}> configured in source/vocabs-uplift.yml"
            )

        # keep everything except the old concepts, which are replaced by those from the CSV
        meta_concepts = set(meta.subjects(RDF.type, SKOS.Concept)) | set(meta.subjects(SKOS.inScheme, scheme))
        dropped = meta_concepts | concepts
        dropped_bnodes = _bnode_closure(meta, dropped)
        for s, p, o in meta:
            if s in dropped or s in dropped_bnodes:
                continue
            if p in (SKOS.hasTopConcept, SKOS.topConceptOf):
                continue
            if o in meta_concepts and o not in concepts:
                continue
            out.add((s, p, o))
        for prefix, ns in meta.namespaces():
            out.bind(prefix, ns, override=True, replace=True)

        # report concept-level changes relative to the published vocabulary
        if vocab.published.is_file():
            old = Graph().parse(vocab.published) if meta_source != vocab.published else meta
            old_concepts = set(old.subjects(RDF.type, SKOS.Concept))
            added, removed = concepts - old_concepts, old_concepts - concepts
            modified = {
                c for c in concepts & old_concepts
                if {(p, o) for p, o in generated.predicate_objects(c) if not (p == SKOS.definition and str(o) == "")}
                != {(p, o) for p, o in old.predicate_objects(c) if p != SKOS.topConceptOf and not (p == SKOS.definition and str(o) == "")}
            }
            for label, items, g in (("Added", added, generated), ("Removed", removed, old), ("Modified", modified, generated)):
                if items:
                    names = sorted(_label(g, c) for c in items)
                    shown = ", ".join(names[:10]) + (f" … (+{len(names) - 10} more)" if len(names) > 10 else "")
                    vocab.changes.append(f"{label} {len(items)}: {shown}")
    else:
        out.bind("cs", str(scheme))

    # scheme triples from the uplift fill in anything the metadata doesn't provide
    for p, o in generated.predicate_objects(scheme):
        if p == RDF.type or (scheme, p, None) not in out:
            out.add((scheme, p, o))

    for c in concepts:
        for p, o in generated.predicate_objects(c):
            out.add((c, p, o))
        for b in _bnode_closure(generated, {c}):
            for p, o in generated.predicate_objects(b):
                out.add((b, p, o))
        if (c, SKOS.definition, None) not in out:
            out.add((c, SKOS.definition, Literal("")))
        if not any(b in concepts for b in out.objects(c, SKOS.broader)):
            out.add((c, SKOS.topConceptOf, scheme))
            out.add((scheme, SKOS.hasTopConcept, c))

    missing_definitions = sum(1 for c in concepts if str(generated.value(c, SKOS.definition) or "") == "")
    if missing_definitions:
        vocab.warnings.append(f"{missing_definitions} of {len(concepts)} concepts have no definition in the CSV")

    concept_ns = {namespace_of(c) for c in concepts}
    if len(concept_ns) == 1:
        out.bind("", concept_ns.pop(), override=True, replace=True)

    if vocab.published.is_file() and meta_source is not None:
        vocab.unchanged = isomorphic(out, Graph().parse(vocab.published))
        if not vocab.unchanged and vocab.changes and (scheme, SDO.dateModified, None) in out:
            out.set((scheme, SDO.dateModified, Literal(datetime.date.today().isoformat(), datatype=XSD.date)))

    return out


def namespace_of(iri) -> str:
    s = str(iri)
    return s[: max(s.rfind("/"), s.rfind("#")) + 1]


# --------------------------------------------------------------------------------------
# 3. Validate
# --------------------------------------------------------------------------------------


def manifest_vocab_resources(manifest: Graph) -> list[tuple[list[str], object]]:
    """(artifact paths, validator) for each ResourceData resource in the manifest."""
    resources = []
    for resource in manifest.objects(None, PROF.hasResource):
        if (resource, PROF.hasRole, MRR_RESOURCE_DATA) not in manifest:
            continue
        artifacts = []
        for artifact in manifest.objects(resource, PROF.hasArtifact):
            if isinstance(artifact, BNode):
                artifact = manifest.value(artifact, SDO.contentLocation)
            artifacts.append(str(artifact))
        resources.append((artifacts, manifest.value(resource, DCTERMS.conformsTo)))
    return resources


def artifact_matches(artifact: str, path: str) -> bool:
    if "*" not in artifact:
        return artifact == path
    prefix, pattern = artifact[: artifact.find("*")], artifact[artifact.find("*"):]
    if not path.startswith(prefix):
        return False
    rest = path[len(prefix):]
    return fnmatch.fnmatch(rest, pattern) or fnmatch.fnmatch(rest, pattern.replace("**/", ""))


def load_shapes(validator) -> Graph:
    """Resolves a manifest validator (a known validator IRI or a local file) to a shapes graph."""
    if isinstance(validator, URIRef):
        if not kurra.shacl.check_validator_known(str(validator)):
            raise RuntimeError(f"The validator <{validator}> declared in manifest.ttl is not known to the Semantic Background")
        validator_id = kurra.shacl.list_local_validators()[str(validator)]["id"]
        shapes = Graph()
        shapes += kurra.shacl.get_validator_graph(validator_id)
        return shapes
    return Graph().parse(REPO_DIR / str(validator))


def validate_drafts(vocabs: list[Vocab]):
    manifest = Graph().parse(MANIFEST_FILE)
    resources = manifest_vocab_resources(manifest)
    background = get_background_graph(MANIFEST_FILE)
    shapes_cache: dict = {}

    for vocab in vocabs:
        if not vocab.draft.is_file():
            continue
        log(f"  validating {vocab.rel_ttl.as_posix()}")
        try:
            data = Graph().parse(vocab.draft)
        except Exception as e:
            vocab.errors.append(f"Draft is not valid Turtle: {e}")
            continue

        matches = [validator for artifacts, validator in resources if any(artifact_matches(a, vocab.manifest_path) for a in artifacts)]
        if not matches:
            vocab.errors.append(
                f"`{vocab.manifest_path}` is not listed in manifest.ttl, so Prez will not load it - "
                "add it to the Resource Data artifacts"
            )
            continue
        validator = matches[0]
        if validator is None:
            continue
        if validator not in shapes_cache:
            shapes_cache[validator] = load_shapes(validator)

        conforms, _, text, _ = kurra.shacl.validate([data, background], shapes_cache[validator])
        if not conforms:
            vocab.errors.append(f"Does not conform to <{validator}>:\n\n```\n{_truncate(text)}\n```")


def _truncate(text: str) -> str:
    lines = text.strip().splitlines()
    if len(lines) <= MAX_RESULT_LINES:
        return "\n".join(lines)
    return "\n".join(lines[:MAX_RESULT_LINES] + [f"... ({len(lines) - MAX_RESULT_LINES} more lines)"])


def validate_staged_manifest(vocabs: list[Vocab]) -> str | None:
    """Validates the full manifest, as Prez would load it, with the drafts in place."""
    with tempfile.TemporaryDirectory(prefix="icsm-vocabs-stage-") as stage:
        stage_dir = Path(stage)
        for item in REPO_DIR.iterdir():
            if item.name in (".git", "source", ".github", "scripts", "tests"):
                continue
            if item.is_dir():
                shutil.copytree(item, stage_dir / item.name)
            else:
                shutil.copy2(item, stage_dir / item.name)
        for vocab in vocabs:
            if vocab.draft.is_file():
                target = stage_dir / "vocabs" / vocab.rel_ttl
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(vocab.draft, target)
        try:
            validate_manifest(stage_dir / MANIFEST_FILE.name)
        except (ManifestValidationError, SyntaxError, ValueError, RuntimeError) as e:
            return str(e).replace(str(stage_dir), "<repo>")
    return None


# --------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------


def write_report(vocabs: list[Vocab], manifest_error: str | None, passed: bool, path: Path | None) -> str:
    failed = [v for v in vocabs if v.errors]
    lines = [
        "# Vocabulary build report",
        "",
        f"Generated {datetime.datetime.now().isoformat(timespec='seconds')} by `scripts/build_vocabs.py`.",
        "",
        f"**Result: {'PASSED' if passed else 'FAILED'}** - {len(vocabs)} vocabularies built, "
        f"{len(failed)} failed validation"
        + (", manifest validation failed" if manifest_error else "")
        + ".",
        "",
    ]
    if not passed:
        lines += [
            "Nothing has been published to `vocabs/`. The generated drafts are in `source/ttl-drafts/`. "
            "Fix the CSVs (or the scheme metadata) and run the build again.",
            "",
        ]
    lines += ["| Vocabulary | Concepts | Status | Changes |", "|---|---:|---|---|"]
    for v in vocabs:
        if v.errors:
            status, changes = "❌ failed", "<br>".join(v.changes)
        elif v.unchanged:
            status, changes = "✅ unchanged", ""
        else:
            status, changes = "✅ passed", "<br>".join(v.changes) or "scheme metadata/formatting only"
        lines.append(f"| `{v.csv.as_posix()}` | {v.concept_count or ''} | {status} | {changes} |")
    lines.append("")

    if manifest_error:
        lines += ["## Manifest validation", "", "```", _truncate(manifest_error), "```", ""]

    if failed:
        lines += ["## Errors", ""]
        for v in failed:
            lines += [f"### `{v.csv.as_posix()}`", ""]
            for e in v.errors:
                lines += [f"- {e}" if "\n" not in e else e, ""]

    warned = [v for v in vocabs if v.warnings]
    if warned:
        lines += ["## Warnings", ""]
        for v in warned:
            for w in v.warnings:
                lines.append(f"- `{v.csv.as_posix()}`: {w}")
        lines.append("")

    report = "\n".join(lines)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(report + "\n")
    return report


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--filter",
        help="Only process CSVs whose path matches this regular expression, e.g. 'wa-.*'",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Build and validate, but always leave the drafts and report in source/ttl-drafts/",
    )
    parser.add_argument(
        "--skip-manifest-validation",
        action="store_true",
        help="Skip the final whole-manifest prezmanifest validation (faster, for local iteration)",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if DRAFTS_DIR.exists():
        log(f"Removing previous drafts in {DRAFTS_DIR.relative_to(REPO_DIR).as_posix()}/")
        shutil.rmtree(DRAFTS_DIR)

    log("1/4 Uplifting CSV sources")
    with tempfile.TemporaryDirectory(prefix="icsm-vocabs-uplift-") as work:
        uplifted, uplift_log = uplift(Path(work), args.filter)
        if not uplifted:
            log("No CSV files matched - nothing to do")
            return 0

        log(f"2/4 Building {len(uplifted)} drafts in {DRAFTS_DIR.relative_to(REPO_DIR).as_posix()}/")
        vocabs = []
        for rel, ttl in uplifted.items():
            vocab = Vocab(rel)
            vocabs.append(vocab)
            if not ttl.is_file():
                vocab.errors.append("Uplift produced no output - see the ogc.na.ingest_json log below")
                vocab.errors.append(f"```\n{_truncate(uplift_log)}\n```")
                continue
            check_csv(vocab)
            if vocab.errors:
                continue
            try:
                g = build(vocab, Graph().parse(ttl))
            except Exception as e:
                vocab.errors.append(f"Build failed: {e}")
                continue
            if g is not None:
                vocab.draft.parent.mkdir(parents=True, exist_ok=True)
                g.serialize(vocab.draft, format="longturtle", encoding="utf-8")

    log("3/4 Validating drafts against the manifest's loading requirements")
    validate_drafts(vocabs)

    manifest_error = None
    if not any(v.errors for v in vocabs) and not args.skip_manifest_validation:
        log("  validating the whole manifest with the drafts in place (prezmanifest)")
        manifest_error = validate_staged_manifest(vocabs)

    passed = not manifest_error and not any(v.errors for v in vocabs)
    publish = passed and not args.no_publish

    report = write_report(vocabs, manifest_error, passed, None if publish else REPORT_FILE)

    if publish:
        log("4/4 Publishing drafts to vocabs/")
        updated = 0
        for vocab in vocabs:
            if not vocab.unchanged:
                vocab.published.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(vocab.draft, vocab.published)
                updated += 1
                log(f"  updated {vocab.published.relative_to(REPO_DIR).as_posix()}")
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        log(f"Done: {updated} updated, {len(vocabs) - updated} unchanged")
        return 0

    log("4/4 Not publishing")
    log("")
    log(report)
    log("")
    log(f"Drafts and report left in {DRAFTS_DIR.relative_to(REPO_DIR).as_posix()}/")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
