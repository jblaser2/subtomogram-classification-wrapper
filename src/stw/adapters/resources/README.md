# Vendored preview-mode scripts

`dynamo_classify_py.py`, `pytom_classify_py.py`, `protomo_classify_py.py` are
vendored verbatim from the STA benchmark project's standalone Python ports
(`packages/{dynamo,PyTom,protomo}/python_port/`) — lightweight, dependency-free
(numpy/scipy/scikit-learn/mrcfile only) approximations of each package's real
classifier, built there by reading each package's own source/compiled binary.
They are wrapped, not reimplemented, by `stw.adapters.preview.*` — see each
adapter module's docstring for the fidelity caveats measured in that project
(closely matches the real package for PyTom; more approximate for Dynamo;
weak/exploratory for ProTomo). `mode: preview` is an explicit opt-in, not the
default — `stw`'s default is always to run a package's real, native
implementation where an adapter for it exists.

Do not edit these files to "improve" the algorithm without also updating the
fidelity numbers in the corresponding adapter docstring — their value is being
a faithful, source-verified approximation, not a best-effort classifier.
