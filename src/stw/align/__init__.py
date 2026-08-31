"""
`stw align` — real global alignment (PyTom's FRM) for roughly-aligned input,
producing a new directory of finely-aligned MRCs that feeds straight into a
normal `stw run` (alignment_state: fine). Not an Adapter: alignment has no
k/seed/class-label contract, so it gets its own small config/report types
rather than being shoehorned into the classification Adapter ABC.

Only one aligner exists today (`pytom_frm`) -- see its module docstring for
why PyTom's FRM was chosen over STA's own hand-rolled aligner and Dynamo's
`dalign`.
"""
from stw.align.config import AlignConfig
from stw.align.pytom_frm import AlignReport, check_installed, run_pytom_alignment

__all__ = ["AlignConfig", "AlignReport", "check_installed", "run_pytom_alignment"]
