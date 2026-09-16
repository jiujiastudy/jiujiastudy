# Time zone files for the offline tests

TZif files for the five zones the fixtures use, copied from the `tzdata`
Python package 2026.3 (IANA tz 2026c). The IANA tz data is in the public
domain.

The harness points `PYTHONTZPATH` here so every platform, including a
Windows Python with no `tzdata` package, reads the same rules offline.
