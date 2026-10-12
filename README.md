# ICSM Vocabularies

This repository contains the source data for [Intergovernmental Committee on Surveying and Mapping](https://icsm.gov.au/)'s vocabularies, that is managed structured lists of terms.

The vocabularies are formulated according to the [Simple Knowledge Organization System (SKOS)](https://www.w3.org/TR/skos-reference/) model and will be display online in human- and machine-readable form in Q1, 2025.

Some of the vocabularies here are in test display online at:

* [Queensland Spatial Information's Vocabs](https://vocabs.gsq.digital/v#qsi-vocabs)

## Copyright & License

These vocabularies are all &copy; ICSM, 2025, unless otherwise indicated within the vocabulary.

All content of this repository is licensed for reuse with the [Creative Commons BY 4.0](https://creativecommons.org/licenses/by/4.0/) licence, in accordance with Australian Government open data policy.


## Contact

The following people are contacts for different aspects of this repository:

_Overall administration_  
_Land Parcel vocabularies_    
**Roger Fraser**  
Victoria Department of Transport and Planning  
<roger.fraser@transport.vic.gov.au>

_Addresses vocabularies_  
_Transport Networks vocabularies_  
**Chair Addressing Working Group**  
_Intergovernmental Committee on Surveying and Mapping_  
<icsm@ga.gov.au>  

_Geographical Names vocabularies_  
**Chair Place Names Working Group**  
_Intergovernmental Committee on Surveying and Mapping_  
<icsm@ga.gov.au>  


_Technical content_  
**Nicholas Car**  
<nick@kurrawong.ai>


## Prez resources

This listing of the resources in this repository is used by the [Prez System](https://kurrawong.ai/products/prez/) to display the vocabularies correctly.


| Resource             | Location                                                                                                              | Notes                                                   |
|----------------------|-----------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------|
| Catalogue Definition | `catalogue.ttl`                                                                                                       |                                                         |
| Items                | `./vocabs/**/*.ttl`                                                                                                   | Multiple ttl files in multiple subfolders               |
| Profile Definition   | [Prez Records Profile](https://github.com/RDFLib/prez/blob/main/prez/reference_data/profiles/ogc_records_profile.ttl) | Default Prez profile for Records API                    |
| Context Resources    | `_background/*.ttl`                                                                                                   | Multiple labels files for ontologies, licenses & agents |

The vocabularies are validated against the conformance claim in `manifest.ttl` (`dcterms:conformsTo <https://linked.data.gov.au/def/vocpub/validator>`, the [VocPub](https://w3id.org/profile/vocpub) profile), using [prezmanifest](https://pypi.org/project/prezmanifest/) with `labels.ttl` as background. This is what must pass for Prez to load them.


## Building vocabularies from CSV

Many of the vocabularies in `vocabs/` (currently all the Land Parcels ones) are maintained as CSV files in `source/`, one CSV per vocabulary, mirroring the `vocabs/` folder layout:

```
source/LandParcels/Parcels/nz-parcel-state.csv  ->  vocabs/LandParcels/Parcels/nz-parcel-state.ttl
```

**Edit the CSV, not the published `.ttl`** - concepts in the published file are regenerated from the CSV on every build.

### How the build works

`scripts/build_vocabs.py` runs the whole process:

1. **Uplift** - every `source/**/*.csv` is converted to RDF by [ogc-na-tools](https://github.com/opengeospatial/ogc-na-tools) using `source/vocabs-uplift.yml` (configured by `.ogc/catalog.ttl`). Each CSV row becomes a `skos:Concept`; its IRI is the vocabulary's base IRI plus the row's `notation` (or `preflabel` if there is no notation).
2. **Build** - each vocabulary's concepts are combined with its `skos:ConceptScheme` metadata (definition, creator, publisher, dates, status, keywords, history notes, etc.) to produce a draft Turtle file in `source/ttl-drafts/`. The scheme metadata is taken from the existing published file in `vocabs/`, or from a `<name>.meta.ttl` sidecar file next to the CSV if one exists. Top concepts are worked out automatically, and `schema:dateModified` is set to today whenever concepts change.
3. **Validate** - each draft must
    * have unique concept IDs (no two CSV rows with the same notation),
    * be listed in `manifest.ttl`, and
    * conform to the validator declared in `manifest.ttl`.

   If all the drafts pass, the whole manifest is then validated with prezmanifest, with the drafts in place, exactly as Prez would load it.
4. **Publish or report**
    * **All passed:** the drafts are moved into `vocabs/` (only files whose content actually changed are rewritten) and `source/ttl-drafts/` is deleted.
    * **Anything failed:** nothing in `vocabs/` is touched. The drafts are left in `source/ttl-drafts/` along with `source/ttl-drafts/validation-report.md`, which lists each vocabulary's status, the concepts added/removed/modified, and every validation error. Fix the CSV (or metadata) and run the build again.

### Running it on GitHub

The [Build vocabularies from CSV sources](.github/workflows/build-vocabs.yml) workflow runs the build automatically when CSVs, `source/vocabs-uplift.yml`, `.ogc/`, `manifest.ttl` or `labels.ttl` change on `main`, and can be run manually from the Actions tab. It commits the result back to `main`:

* on success, the updated `vocabs/` files;
* on failure, the `source/ttl-drafts/` folder with the report. The run is then marked as failed, the report is shown in the run's summary page, and the drafts are also attached to the run as a downloadable artifact. The next successful build removes `source/ttl-drafts/`.

### Running it locally

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r scripts/requirements.txt

python scripts/build_vocabs.py
```

The script exits with status 0 if the vocabularies were published and 1 if validation failed. Useful options:

| Option | Effect |
|---|---|
| `--filter REGEX` | Only build CSVs whose path matches, e.g. `--filter 'wa-.*'` |
| `--no-publish` | Build and validate, but always leave the drafts and report in `source/ttl-drafts/` so you can inspect them |
| `--skip-manifest-validation` | Skip the final whole-manifest validation (takes a few minutes); the per-vocabulary checks still run |

The first run downloads and caches the validators known to the [Kurrawong Semantic Background](https://kurrawong.ai) in `~/.kurra`, so it needs internet access.

### Adding a new CSV vocabulary

1. Add the CSV under `source/` in the folder it should be published in. Columns: `preflabel`, `definition`, `notation`, `altlabel` (`related` is ignored). Each `notation` must be unique.
2. Add an entry for the file to the `csMapping` in `source/vocabs-uplift.yml`, giving the ConceptScheme `uri`, `label` and concept `type`. If the concept IRIs should be in a different namespace from the scheme (as for the EPSG CRS vocabularies), add `base` as well.
3. Create `<name>.meta.ttl` next to the CSV describing the ConceptScheme (with the same IRI as in step 2) - see any published vocabulary for the required properties. Once the vocabulary has been published, its metadata is maintained in the published file and the sidecar can be deleted.
4. Add `vocabs/<path>/<name>.ttl` to the Resource Data artifacts in `manifest.ttl`.
5. Run the build.


### Vocab testing process

1. Install packages listed in tests/requirements.txt
2. Use scripts top validate all vocabs: `pytest`
3. Use `tests/labelify_all.py` to identify any missing labels
    * add any missing to `_background`
4. Manually create/update the `cattalogue.ttl` file
