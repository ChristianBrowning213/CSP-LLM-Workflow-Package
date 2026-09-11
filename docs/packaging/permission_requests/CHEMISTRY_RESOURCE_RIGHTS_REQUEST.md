# Chemistry and radii resource rights review request

To: QLIP resource maintainer and appropriate project/institutional rights
reviewer

The QLIP distribution bundles generated JSON tables under
`packages/qlip/src/qlip/resources/base/`. Their provenance identifies ASE
3.27.0, mendeleev 1.1.0, pymatgen 2026.5.4, and SMACT 4.0.0, plus scientific
literature sources. The current record does not establish the rights and notice
requirements for redistribution of the compiled values.

Please provide or confirm:

1. the exact upstream files/APIs used for every generated field;
2. the applicable software, database, and data licences at those versions;
3. whether the transformation creates a redistributable compilation;
4. required licence notices and scientific citations; and
5. authority to distribute the existing exact JSON tables.

If redistribution is not confirmed, a future task may generate values from
declared dependencies at build/runtime only if an exhaustive regression test
proves parity with the existing tables. This request does not authorize a
scientific-value change.
