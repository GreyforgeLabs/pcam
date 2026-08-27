# PCAM-24 Profile

Status: DRAFT

PCAM-24 provides a 24-cell authoring and visualization profile that compiles into ordinary PCAM Core definitions. Ranges are half-open, tags may overlap, wrapping ranges are forbidden, lifecycle behavior is explicit, and the compiled Core definition is the normative execution artifact.

Required compatibility statement:

> The phase value is one projected coordinate of a larger authoritative action state. Equal phase values do not imply equal complete states.

Implementation evidence will live beside the compiler and in `tests/vectors/`.
