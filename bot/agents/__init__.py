from .base import Agent
from .news import NewsAgent
from .scanner import ScannerAgent
from .technical import TechnicalAgent
from .correlation import CorrelationAgent
from .learning import LearningAgent
from .risk import RiskAgent
from .execution import ExecutionAgent
from .oraculo import OracleAgent

__all__ = ["Agent", "NewsAgent", "ScannerAgent", "TechnicalAgent",
           "CorrelationAgent", "LearningAgent", "RiskAgent", "ExecutionAgent", "OracleAgent"]
