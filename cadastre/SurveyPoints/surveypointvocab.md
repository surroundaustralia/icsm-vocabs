# Survey Point Vocabularies

<!--
:Author:    Andrew Hunter
:Email:     <andrew@edgegeomatics.co.nz>
:Date:      8 May 2023
:Revision:  0.1
-->



To start to build jurisdictional profiles that are customised to meet the specific needs of the NZ, VIC and WA
jurisdictions we need to document and agree on the vocabularies and patterns (naming patterns for Survey Points) that
will be used by each jurisdiction.

The intent of this page is to describe the information that is required in order for the Surround team to build the
Survey Point profile components.

## Background

The class **Survey Point** in the CSDM is depicted in the [Survey Point Class Diagram](./images/Survey_Marks.png) below. A **Survey Point**
is any point of interest in a survey. It may relate to a boundary corner (marked or unmarked), a cadastral mark, a
geodetic reference mark, or an occupation mark. The [Survey Point Class Diagram](./images/Survey_Marks.png) includes definitions of each of
the classes and class attributes defined the requirements identified during the first phase of the development of the 3D
CSDM. A number of the attributes are or may be controlled vocabularies in accordance with jurisdictional code lists.
Phase I also identified that some jurisdictions utilise compound naming patterns to describe Survey Points.

<figure id="fig1">
<img src="./images/Survey_Marks.png" alt="Survey Point Class Diagram" />
<figcaption aria-hidden="true">Figure 1: Survey Point Class Diagram</figcaption>
</figure>

The initial code lists identified include:

1. Survey Mark Purpose

2. Positional Quality

3. Survey Mark State

4. Survey Mark Condition

5. Survey Mark Monument Type

Initial vocabularies have been generated from jurisdictional documentation and discussion with each of the
jurisdictions. Initial vocabularies in CSV and JSON-LD can be [found here](../enum/).

The files are organised generally as follows:

| preflabel                    | definition | notation  | altlabel | related |
|------------------------------|------------|-----------|----------|---------|
| Boundary Accepted            |            | NOWP:BACC |          |         |
| Boundary Defined by Adoption |            | NOWP:BNDA |          |         |
| Boundary Defined by Survey   |            | NOWP:BNDS |          |         |

#### Example Vocabulary for Survey Mark Purpose (LINZ)

The definitions for the header row are:

**preflabel**: Preferred Label used to assign an authorized name to a survey mark purpose.

**definition**: A complete explanation of the intended meaning of a preflabel.

**notation**: In a knowledge system (SKOS) a notation is a string of characters that uniquely identify a concept.
In [Example Vocabulary for Survey Mark Purpose (LINZ)](#example-vocabulary-for-survey-mark-purpose-linz) the unique identifier for the preferred label **Boundary
Defined by Survey** is **NOWP:BNDS**.

**altlabel**: Is there an alternative label, perhaps informally used in place of an authorized name, e.g., wooden peg
might be an alternative name for a boundary mark.

**related**: Is this preflabel related to another preflabel, e.g., is the VIC survey mark State "destroyed" related to
the NZ survey mark State "destroyed"?

## Objective

1. Document Survey Mark vocabularies that are to be included in the CSDM.

2. Where practicable, identify and agree on vocabularies that can be harmonized.

3. Identify if a jurisdictional compound name pattern is required for Survey Points, and if so, what is the pattern.