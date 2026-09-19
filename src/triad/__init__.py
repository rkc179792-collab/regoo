"""Triad: a Tracker, a Predictor, and a Commander that gate a release."""

from triad.config import Config
from triad.crew import Crew
from triad.models import Verdict

__version__ = "0.1.0"
__all__ = ["Config", "Crew", "Verdict", "__version__"]
