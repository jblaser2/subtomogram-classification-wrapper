"""
stw's local web GUI. Not imported by the core library — `import stw` never
pulls in FastAPI/uvicorn/matplotlib; this subpackage is only touched by the
`stw gui` CLI command, which lazily imports it and gives a clear error if the
`gui` extra isn't installed.
"""
