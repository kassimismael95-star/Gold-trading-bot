from core.bot_manager import BotManager, MarketState
from core.risk_manager import RiskManager
from core.signal_engine import MicroMomentumTracker


risk_manager = RiskManager()
signal_tracker = MicroMomentumTracker()
bot_manager = BotManager(
    risk_manager=risk_manager,
    signal_tracker=signal_tracker,
)


def make_market(
    open_positions=None,
    balance=100.00,
    equity=100.00,
    free_margin=100.00,
    spread_pips=10.0,
):
    return MarketState(
        bid=3300.00,
        ask=3300.10,
        spread_pips=spread_pips,
        free_margin=free_margin,
        balance=balance,
        equity=equity,
        open_positions=open_positions or [],
    )


def test_first_entry_is_buy_when_confidence_is_positive():
    market = make_market()

    plan = bot_manager.decide(
        market=market,
        direction="BUY",
        confidence=6,
        recent_price_movement=0.20,
    )

    assert plan.action == "OPEN_POSITION"
    assert plan.direction == "BUY"
    assert plan.volume == 0.04
    assert plan.position_number == 1
    assert plan.stop_loss < market.ask
    assert plan.take_profit > market.ask


def test_first_entry_is_sell_when_confidence_is_negative():
    market = make_market()

    plan = bot_manager.decide(
        market=market,
        direction="SELL",
        confidence=-6,
        recent_price_movement=0.20,
    )

    assert plan.action == "OPEN_POSITION"
    assert plan.direction == "SELL"
    assert plan.volume == 0.04
    assert plan.position_number == 1
    assert plan.stop_loss > market.bid
    assert plan.take_profit < market.bid


def test_first_entry_blocks_high_spread():
    market = make_market(spread_pips=40.0)

    plan = bot_manager.decide(
        market=market,
        direction="BUY",
        confidence=6,
        recent_price_movement=0.20,
    )

    assert plan.action == "HOLD"
    assert "Spread" in plan.reason


def test_first_entry_blocks_during_cooldown():
    market = make_market()

    bot_manager.reset_batch()

    plan = bot_manager.decide(
        market=market,
        direction="BUY",
        confidence=6,
        recent_price_movement=0.20,
    )

    assert plan.action == "HOLD"
    assert "cooldown" in plan.reason.lower()


def test_basket_profit_target_closes_basket():
    market = make_market(
        open_positions=[
            {
                "symbol": "XAUUSDm",
                "profit": 2.50,
            },
            {
                "symbol": "XAUUSDm",
                "profit": 2.00,
            },
        ],
        balance=100.00,
        equity=104.50,
    )

    plan = bot_manager.decide(
        market=market,
        direction="BUY",
        confidence=6,
        recent_price_movement=0.20,
    )

    assert plan.action == "CLOSE_BASKET"
    assert "Basket profit target reached" in plan.reason


def test_35_percent_drawdown_closes_basket():
    market = make_market(
        open_positions=[
            {
                "symbol": "XAUUSDm",
                "profit": -40.00,
            },
        ],
        balance=100.00,
        equity=60.00,
    )

    plan = bot_manager.decide(
        market=market,
        direction="BUY",
        confidence=6,
        recent_price_movement=0.20,
    )

    assert plan.action == "CLOSE_BASKET"
    assert "35% drawdown circuit breaker" in plan.reason


def test_add_position_when_original_conditions_are_met():
    market = make_market(
        open_positions=[
            {
                "symbol": "XAUUSDm",
                "profit": 1.00,
            },
        ],
        balance=100.00,
        equity=101.00,
        free_margin=100.00,
        spread_pips=10.0,
    )

    bot_manager.register_first_entry(
        direction="BUY",
        market=market,
    )

    market.ask = 3300.30
    market.bid = 3300.20

    plan = bot_manager.decide(
        market=market,
        direction="BUY",
        confidence=6,
        recent_price_movement=0.20,
    )

    assert plan.action == "OPEN_POSITION"
    assert plan.direction == "BUY"
    assert plan.position_number == 2
    assert plan.volume == 0.05


def test_no_add_position_when_basket_is_losing():
    market = make_market(
        open_positions=[
            {
                "symbol": "XAUUSDm",
                "profit": -1.00,
            },
        ],
        balance=100.00,
        equity=99.00,
        free_margin=100.00,
        spread_pips=10.0,
    )

    bot_manager.register_first_entry(
        direction="BUY",
        market=market,
    )

    market.ask = 3300.30
    market.bid = 3300.20

    plan = bot_manager.decide(
        market=market,
        direction="BUY",
        confidence=6,
        recent_price_movement=0.20,
    )

    assert plan.action == "HOLD"


def test_no_add_position_when_price_has_not_moved_enough():
    market = make_market(
        open_positions=[
            {
                "symbol": "XAUUSDm",
                "profit": 1.00,
            },
        ],
        balance=100.00,
        equity=101.00,
        free_margin=100.00,
        spread_pips=10.0,
    )

    bot_manager.register_first_entry(
        direction="BUY",
        market=market,
    )

    market.ask = 3300.15
    market.bid = 3300.05

    plan = bot_manager.decide(
        market=market,
        direction="BUY",
        confidence=6,
        recent_price_movement=0.20,
    )

    assert plan.action == "HOLD"


def test_no_add_position_when_spread_is_too_high():
    market = make_market(
        open_positions=[
            {
                "symbol": "XAUUSDm",
                "profit": 1.00,
            },
        ],
        balance=100.00,
        equity=101.00,
        free_margin=100.00,
        spread_pips=40.0,
    )

    bot_manager.register_first_entry(
        direction="BUY",
        market=market,
    )

    market.ask = 3300.30
    market.bid = 3300.20

    plan = bot_manager.decide(
        market=market,
        direction="BUY",
        confidence=6,
        recent_price_movement=0.20,
    )

    assert plan.action == "HOLD"


def test_no_add_position_when_free_margin_is_zero():
    market = make_market(
        open_positions=[
            {
                "symbol": "XAUUSDm",
                "profit": 1.00,
            },
        ],
        balance=100.00,
        equity=101.00,
        free_margin=0.00,
        spread_pips=10.0,
    )

    bot_manager.register_first_entry(
        direction="BUY",
        market=market,
    )

    market.ask = 3300.30
    market.bid = 3300.20

    plan = bot_manager.decide(
        market=market,
        direction="BUY",
        confidence=6,
        recent_price_movement=0.20,
    )

    assert plan.action == "HOLD"


def test_no_add_position_at_18_position_hard_limit():
    positions = []

    for position_number in range(18):
        positions.append(
            {
                "symbol": "XAUUSDm",
                "profit": 1.00,
            }
        )

    market = make_market(
        open_positions=positions,
        balance=100.00,
        equity=118.00,
        free_margin=100.00,
        spread_pips=10.0,
    )

    bot_manager.register_first_entry(
        direction="BUY",
        market=market,
    )

    market.ask = 3300.30
    market.bid = 3300.20

    plan = bot_manager.decide(
        market=market,
        direction="B
