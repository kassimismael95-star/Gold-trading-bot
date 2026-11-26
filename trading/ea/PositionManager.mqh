
#ifndef GOLD_PROFIT_MANAGER
#define GOLD_PROFIT_MANAGER

#include "BasketManager.mqh"

class CProfitManager
{
private:
   CBasketManager basket;

public:

   // Retain basket-profit reporting for account monitoring.
   double BasketProfit(string symbol, long magic)
   {
      return basket.Profit(symbol, magic);
   }

   // Fixed basket-profit closure is disabled.
   // Each position must instead be managed independently
   // by the intelligent position-management system.
   bool TargetReached(double profit, double target)
   {
      return false;
   }
};

#endif
