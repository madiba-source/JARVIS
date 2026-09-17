# Filesystem Control Operations

Filesystem operations are confined to the configured workspace root. Paths are canonicalized, traversal is rejected, symlink components are rejected, and destructive directory recursion is not implemented.

Read operations bound file size, directory entries, and search results. Writes use bounded UTF-8 payloads and temporary-file replacement. Copy and move accept regular files only. Delete accepts regular files only and requires L3 confirmation.

All operations enter the typed policy registry, use an execution lease, return typed execution results, and verify their postcondition. Complete file contents are not written to audit records.
