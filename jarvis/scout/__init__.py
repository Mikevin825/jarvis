"""The scout sub-agent.

A research loop that hunts for competitor/product news, scores what it finds
against a rubric, and hands the results to a human who decides.

The instruction set is data, not code. The doctrine lives in DOCTRINE.md
(Tier 2), and the research loop is the engine that executes it.
"""

from .loop import ResearchLoopConfig, run_research_loop
from .report import Finding, ScoutReport
from .tools import build as build_research_tools

__all__ = [
    "Finding",
    "ResearchLoopConfig",
    "ScoutReport",
    "build_research_tools",
    "run_research_loop",
]
