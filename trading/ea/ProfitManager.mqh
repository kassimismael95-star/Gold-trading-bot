
#ifndef GOLD_PROFIT_MANAGER
#define GOLD_PROFIT_MANAGER

#include "BasketManager.mqh"

// Gold Scalper AI profit reporting.
//
// Basket profit is calculated for monitoring and telemetry only.
// Individual positions are managed by CPositionManager.
//
// There is deliberately no automatic basket-profit close.
class CProfitManager
{
private:
   CBasketManager basket;

public:

   // Return combined floating profit for reporting.
   double BasketProfit(
      string symbol,
      long magic
   )
   {
      return basket.Profit(symbol, magic);
   }

   // Retained for compatibility with existing callers.
   // Automatic basket-profit closure is disabled.
   bool TargetReached(
      double profit,
      double target
   )
   {
      return false;
   }
};

#endif
