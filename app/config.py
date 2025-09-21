from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    tradier_access_token: str = Field(default="", alias="TRADIER_ACCESS_TOKEN")
    tradier_env: str = Field(default="sandbox", alias="TRADIER_ENV")
    tradier_account_id: str = Field(default="", alias="TRADIER_ACCOUNT_ID")
    polygon_api_key: str = Field(default="", alias="POLYGON_API_KEY")

    dry_run: int = Field(default=1, alias="DRY_RUN")
    scan_interval_sec: int = Field(default=30, alias="SCAN_INTERVAL_SEC")
    port: int = Field(default=8080, alias="PORT")

    # Strategy
    symbols: str = Field(default="AAPL,MSFT,TSLA,SPY,QQQ", alias="SYMBOLS")
    default_qty: int = Field(default=1, alias="ORDER_QTY")
    strategy_interval: str = Field(default="1m", alias="STRATEGY_INTERVAL")  # 1m|5m|1d
    lookback_min: int = Field(default=180, alias="LOOKBACK_MIN")
    lookback_days: int = Field(default=120, alias="LOOKBACK_DAYS")

    # Risk Guardrails
    risk_max_concurrent: int = Field(default=3, alias="RISK_MAX_CONCURRENT")
    risk_max_open_orders: int = Field(default=5, alias="RISK_MAX_OPEN_ORDERS")
    risk_max_positions_per_symbol: int = Field(default=1, alias="RISK_MAX_POSITIONS_PER_SYMBOL")
    risk_max_order_notional_usd: float | None = Field(default=None, alias="RISK_MAX_ORDER_NOTIONAL_USD")
    trading_window_start: str = Field(default="09:31", alias="TRADING_WINDOW_START")  # America/New_York
    trading_window_end: str = Field(default="15:55", alias="TRADING_WINDOW_END")
    symbol_whitelist: str = Field(default="", alias="SYMBOL_WHITELIST")
    symbol_blacklist: str = Field(default="", alias="SYMBOL_BLACKLIST")
    min_cash_usd: float | None = Field(default=None, alias="MIN_CASH_USD")

    # Bracket exits (percent as decimal, e.g., 0.01 = 1%)
    stop_pct: float | None = Field(default=None, alias="STOP_PCT")
    tp_pct: float | None = Field(default=None, alias="TP_PCT")

    # Trailing stop (optional)
    trail_pct: float | None = Field(default=None, alias="TRAIL_PCT")
    trail_activation_pct: float | None = Field(default=None, alias="TRAIL_ACT_PCT")

    class Config:
        env_file = ".env"
        case_sensitive = False


def settings() -> Settings:
    return Settings()  # loads from environment/.env
