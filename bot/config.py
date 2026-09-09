"""Configuracion central del sistema multi-agente."""
from dataclasses import dataclass, field, asdict


@dataclass
class Instrument:
    symbol: str          # identificador interno, p.ej. "BTC-USD"
    venue: str           # "kraken" | "yahoo"
    code: str            # codigo en el venue, p.ej. "XBTUSD" | "SPY"
    kind: str            # "crypto" | "equity"
    label: str


UNIVERSE = [
    Instrument("BTC-USD", "kraken", "XBTUSD", "crypto", "Bitcoin"),
    Instrument("ETH-USD", "kraken", "ETHUSD", "crypto", "Ethereum"),
    Instrument("SOL-USD", "kraken", "SOLUSD", "crypto", "Solana"),
    Instrument("SPY", "yahoo", "SPY", "equity", "S&P 500 (SPY)"),
    Instrument("QQQ", "yahoo", "QQQ", "equity", "Nasdaq 100 (QQQ)"),
]


@dataclass
class Config:
    # --- Capital y modo ---
    mode: str = "paper"              # "paper" | "live"  (live NO esta implementado a proposito)
    starting_cash: float = 100.0     # USD

    # --- Riesgo ---
    risk_per_trade: float = 0.02     # 2% del equity arriesgado por operacion
    max_positions: int = 3
    max_position_weight: float = 0.35   # max 35% del equity en un solo activo
    stop_atr_mult: float = 2.0       # stop = entrada - 2*ATR
    take_profit_r: float = 2.0       # objetivo = 2R (2x el riesgo)
    max_drawdown_stop: float = 0.25  # kill switch: -25% desde el pico -> se apaga

    # --- Costes de mercado (simulados de forma realista) ---
    fee_rate: float = 0.0010         # 0.10% por lado
    slippage_rate: float = 0.0005    # 0.05%

    # --- Decision ---
    buy_threshold: float = 0.35      # score compuesto para abrir largo
    exit_threshold: float = -0.15    # score compuesto para cerrar

    # --- Pesos de voto de cada agente ---
    weights: dict = field(default_factory=lambda: {
        "technical": 0.45,
        "scanner": 0.30,
        "news": 0.25,
    })

    # --- Cadencias (segundos) ---
    tick_seconds: int = 20           # ciclo de decision del orquestador
    news_seconds: int = 180
    scanner_seconds: int = 60
    technical_seconds: int = 30

    # --- Mejoras activas ---
    # Elegidas midiendo cada una por separado sobre 402 barras diarias
    # (ver `python3 -m bot.backtest --ablation`). "roi" y "regime" quedan fuera:
    # la escalera ROI cortaba a los ganadores y el filtro de regimen no cambio
    # ni una sola operacion.
    features: tuple = ("adx", "prot", "trail")

    # --- Servidor ---
    host: str = "127.0.0.1"
    port: int = 8787

    def to_dict(self):
        return asdict(self)


CONFIG = Config()
