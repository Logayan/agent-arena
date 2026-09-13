# Claude Agent SDK G3 Probe

This directory is an isolated migration probe. It is not imported by the server, is not registered in the Runtime Registry, and must not contain credentials.

The live probe receives model configuration through environment variables supplied by a wrapper process. Results are allowlisted and redacted before being written or printed.
