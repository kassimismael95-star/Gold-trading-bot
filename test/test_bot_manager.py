import unittest
from unittest.mock import patch, MagicMock

from core.bot_manager import (
    calculate_current_spread_pips,
    calculate_basket_profit,
    should_add_position,
    should_close_basket,
    create_trade_command,
    process_bot_tick
)


class TestBotManager(unittest.TestCase):
    def test_calculate_current_spread_pips(self):
        spread = calculate_current_spread_pips(
            bid=2300.00,
            ask=2300.20
        )

        self.assertEqual(spread, 20.0)

    def test_calculate_basket_profit(self):
        open_positions = [
            {
                "profit": 1.00
            },
            {
                "profit": -0.30
            },
            {
                "profit": 0.50
            }
        ]

        profit = calculate_basket_profit(open_positions)

        self.assertEqual(profit, 1.20)

    def test_should_add_position_when_price_moves_against_buy(self):
        should_add = should_add_position(
            open_positions=[
                {
                    "direction": "BUY",
                    "entry_price": 2300.00
                }
            ],
            max_positions=5,
            direction="BUY",
            current_direction="BUY",
            current_price=2299.70,
            last_entry_price=2300.00
        )

        self.assertTrue(should_add)

    def test_should_not_add_position_when_price_moves_in_favor(self):
        should_add = should_add_position(
            open_positions=[
                {
                    "direction": "BUY",
                    "entry_price": 2300.00
                }
            ],
            max_positions=5,
            direction="BUY",
            current_direction="BUY",
            current_price=2300.30,
            last_entry_price=2300.00
        )

        self.assertFalse(should_add)

    def test_should_not_add_position_when_direction_changes(self):
        should_add = should_add_position(
            open_positions=[
                {
                    "direction": "BUY",
                    "entry_price": 2300.00
                }
            ],
            max_positions=5,
            direction="BUY",
            current_direction="SELL",
            current_price=2299.70,
            last_entry_price=2300.00
        )

        self.assertFalse(should_add)

    def test_should_not_add_position_when_max_reached(self):
        open_positions = [
            {
                "direction": "BUY",
                "entry_price": 2300.00
            },
            {
                "direction": "BUY",
                "entry_price": 2299.80
            }
        ]

        should_add = should_add_position(
            open_positions=open_positions,
            max_positions=2,
            direction="BUY",
            current_direction="BUY",
            current_price=2299.70,
            last_entry_price=2299.80
        )

        self.assertFalse(should_add)

    def test_should_close_basket_when_target_reached(self):
        open_positions = [
            {
                "profit": 0.20
            },
            {
                "profit": 0.15
            }
        ]

        should_close = should_close_basket(
            open_positions=open_positions,
            basket_target=0.35
        )

        self.assertTrue(should_close)

    def test_should_not_close_basket_below_target(self):
        open_positions = [
            {
                "profit": 0.20
            },
            {
                "profit": 0.10
            }
        ]

        should_close = should_close_basket(
            open_positions=open_positions,
            basket_target=0.35
        )

        self.assertFalse(should_close)

    @patch("core.bot_manager.create_command")
    def test_create_trade_command(self, mock_create_command):
        mock_create_command.return_value = {
            "id": "command-1",
            "status": "PENDING"
        }

        command = create_trade_command(
            user_id=1,
            account_id=1,
            bot_session_id=1,
            command_type="OPEN_POSITION",
            symbol="XAUUSD",
            direction="BUY",
            volume=0.01,
            stop_loss=2300.00,
            take_profit=2302.20
        )

        self.assertEqual(command["id"], "command-1")
        self.assertEqual(command["status"], "PENDING")

    @patch("core.bot_manager.get_open_positions_for_session")
    @patch("core.bot_manager.send_trade_command")
    def test_process_bot_tick_waits_on_high_spread(
        self,
        mock_send_trade_command,
        mock_get_positions
    ):
        mock_get_positions.return_value = []

        result = process_bot_tick(
            user_id=1,
            account_id=1,
            bot_session_id=1,
            symbol="XAUUSD",
            current_price=2300.00,
            bid=2299.00,
            ask=2301.00,
            equity=10.00,
            balance=10.00
        )

        self.assertEqual(result["action"], "WAIT")
        self.assertEqual(
            result["reason"],
            "SPREAD_TOO_HIGH"
        )

        mock_send_trade_command.assert_not_called()

    @patch("core.bot_manager.get_open_positions_for_session")
    @patch("core.bot_manager.send_trade_command")
    def test_process_bot_tick_waits_on_low_confidence(
        self,
        mock_send_trade_command,
        mock_get_positions
    ):
        mock_get_positions.return_value = []

        result = process_bot_tick(
            user_id=1,
            account_id=1,
            bot_session_id=1,
            symbol="XAUUSD",
            current_price=2300.00,
            bid=2299.90,
            ask=2300.10,
            equity=10.00,
            balance=10.00
        )

        self.assertEqual(result["action"], "WAIT")
        self.assertEqual(
            result["reason"],
            "LOW_CONFIDENCE"
        )

        mock_send_trade_command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
