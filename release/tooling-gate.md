# Reference Tooling Gate

State: CLOSED for §42

The reference package exposes all eleven recommended commands:

- `validate`
- `compile`
- `canonicalize`
- `definition-hash`
- `run`
- `trace`
- `snapshot`
- `restore`
- `state-hash`
- `rollback-test`
- `migrate-v2`

`../tests/vectors/cli-result-codes.json` is the machine-readable command matrix. It requires, in normative command order:

- one successful invocation of every command with result code `OK` and exit status zero
- one command-specific rejected invocation of every command with its exact stable result code and exit status two
- a missing-file-argument invocation of every command with result code `INVALID_INPUT`, exit status two, valid JSON on stdout, and no stderr
- a nonexistent input path with result code `IO_ERROR` and exit status two

The success path for `snapshot` produces the exact snapshot input used by the successful `restore` and `state-hash` cases. Runtime-oriented success cases use the pinned typed-strike vector, including rollback equivalence.

The command facade normalizes parsing, decoding, shape, and I/O failures into declared `ResultCode` members. Canonicalization and PCAM runtime faults preserve their more specific stable codes and fault identifiers.

Executable evidence is in `../reference/python/tests/test_cli_result_codes.py`. This tooling gate makes no runtime or §37 conformance claim.
