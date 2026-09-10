"""Configuracion central del sistema multi-agente."""
from dataclasses import dataclass, field, asdict


@dataclass
class Instrument:
    symbol: str          # identificador interno, p.ej. "BTC-USD"
    venue: str           # "kraken" | "yahoo"
    code: str            # codigo en el venue, p.ej. "XBTUSD" | "SPY"
    kind: str            # "crypto" | "equity"
    label: str


# Los cinco de siempre se quedaron cortos: con tres criptos, el escaner casi
# nunca tenia entre que elegir y el sistema pasaba semanas mirando los mismos
# graficos. Ahora se opera todo el bloque liquido de Kraken en USD, que es el
# mismo universo sobre el que se hicieron los barridos de bot/sweep.py.
# Solo cripto. Las acciones se van: con $10 o $100 no llega ni para una sola
# accion de SPY (cuesta $758), y ademas solo operan de lunes a viernes en
# horario de Nueva York, asi que la mitad del tiempo el sistema miraba un
# mercado cerrado. Los veinte pares mas liquidos de Kraken en USD.
UNIVERSE = [
    Instrument("BTC-USD", "kraken", "XBTUSD", "crypto", "Bitcoin"),
    Instrument("ETH-USD", "kraken", "ETHUSD", "crypto", "Ethereum"),
    Instrument("XRP-USD", "kraken", "XRPUSD", "crypto", "XRP"),
    Instrument("SOL-USD", "kraken", "SOLUSD", "crypto", "Solana"),
    Instrument("DOGE-USD", "kraken", "XDGUSD", "crypto", "Dogecoin"),
    Instrument("ADA-USD", "kraken", "ADAUSD", "crypto", "Cardano"),
    Instrument("LINK-USD", "kraken", "LINKUSD", "crypto", "Chainlink"),
    Instrument("AVAX-USD", "kraken", "AVAXUSD", "crypto", "Avalanche"),
    Instrument("DOT-USD", "kraken", "DOTUSD", "crypto", "Polkadot"),
    Instrument("LTC-USD", "kraken", "LTCUSD", "crypto", "Litecoin"),
    Instrument("BCH-USD", "kraken", "BCHUSD", "crypto", "Bitcoin Cash"),
    Instrument("UNI-USD", "kraken", "UNIUSD", "crypto", "Uniswap"),
    Instrument("NEAR-USD", "kraken", "NEARUSD", "crypto", "NEAR"),
    Instrument("APT-USD", "kraken", "APTUSD", "crypto", "Aptos"),
    Instrument("ATOM-USD", "kraken", "ATOMUSD", "crypto", "Cosmos"),
    Instrument("FIL-USD", "kraken", "FILUSD", "crypto", "Filecoin"),
    Instrument("ETC-USD", "kraken", "ETCUSD", "crypto", "Ethereum Classic"),
    Instrument("XLM-USD", "kraken", "XLMUSD", "crypto", "Stellar"),
    Instrument("HBAR-USD", "kraken", "HBARUSD", "crypto", "Hedera"),
    Instrument("TRX-USD", "kraken", "TRXUSD", "crypto", "TRON"),
]


@dataclass
class Config:
    # --- Capital y modo ---
    mode: str = "paper"              # "paper" | "live"  (live NO esta implementado a proposito)
    starting_cash: float = 100.0     # USD

    # --- Riesgo ---
    risk_per_trade: float = 0.02     # 2% del equity arriesgado por operacion
    max_positions: int = 5      # mas universo, mas sitio donde repartir
    # Tope por clase de activo. Con 17 criptos daba la impresion de que habia
    # que subirlo; medido, aflojarlo empeora: con 4 el sistema pierde -15.29% y
    # salta el kill switch, con 2 hace +1.09%. Se queda en 2 por medicion, no
    # por costumbre.  (python3 -m bot.backtest --fees)
    max_per_kind: int = 2
    max_position_weight: float = 0.35   # max 35% del equity en un solo activo
    stop_atr_mult: float = 2.0       # stop = entrada - 2*ATR
    take_profit_r: float = 2.0       # objetivo = 2R (2x el riesgo)
    max_drawdown_stop: float = 0.25  # kill switch: -25% desde el pico -> se apaga

    # --- Costes de mercado (simulados de forma realista) ---
    fee_rate: float = 0.0010         # 0.10% por lado
    slippage_rate: float = 0.0005    # 0.05%

    # --- Decision ---
    buy_threshold: float = 0.35      # score compuesto para abrir largo
    short_threshold: float = -0.45   # score compuesto para abrir corto
    allow_shorts: bool = False       # apagado por defecto: hay que demostrarlo
    # Rollover de margen de Kraken, por dia y por dolar en corto. Un backtest de
    # cortos que no lo pague esta inventando dinero.
    short_funding_daily: float = 0.0006
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
