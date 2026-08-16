# Security

## Reporting

Report vulnerabilities through GitHub's private security advisory form on this
repository. Please do not open a public issue for an unfixed vulnerability.

## Scope

judgeguard runs locally and in CI. It reads a corpus, calls retrieval backends you
configure, and writes reports. It has no server component.

In scope:

- the deterministic lane reaching the network, or requiring a credential
- credentials leaking into transcripts, reports or baselines
- corpus content executing rather than being treated as data
- an override that lets a judge score influence an exit code

## The injection pack is deliberate

`corpus/documents.jsonl` contains a document with an embedded instruction and the
marker `JG-PWNED-7781`. It is a test fixture. `judgeguard gate` is expected to fail on
a clean checkout because the bundled naive candidate echoes retrieved text and the
marker surfaces.

That failure is the demonstration, not a vulnerability in judgeguard. Report it if the
check stops firing.

## Transcripts contain retrieved content

A transcript records passages verbatim. If you run judgeguard against a real index,
`.judgeguard/transcripts.jsonl` will contain real retrieved content, including content
that was correctly withheld from the answer.

Treat the output directory at the classification of the most sensitive document in
the index. `.judgeguard/` is gitignored by default — do not remove that entry to make
artifact upload easier.
