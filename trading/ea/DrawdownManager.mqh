
#ifndef GOLD_DRAWDOWN_MANAGER
#define GOLD_DRAWDOWN_MANAGER

class CDrawdownManager
{
public:

   // Account percentage drawdown is not used as an automatic
   // trading breaker in this strategy.
   //
   // Retained for compatibility with AccountRiskMonitor.mqh.
   bool AccountDrawdownExceeded(
      double equity,
      double balance,
      double limitPercent
   )
   {
      return false;
   }

   // Keep the separately configured basket-loss protection.
   bool BasketLossExceeded(
      double basketProfit,
      double maxLossCurrency
   )
   {
      if(maxLossCurrency <= 0.0)
         return false;

      return basketProfit <= -maxLossCurrency;
   }
};

#endif
