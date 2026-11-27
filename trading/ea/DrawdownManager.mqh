
#ifndef GOLD_DRAWDOWN_MANAGER
#define GOLD_DRAWDOWN_MANAGER

class CDrawdownManager
{
public:

   // Fixed account drawdown shutdown is disabled.
   // Open positions must be managed individually by the
   // post-entry intelligence supervisor.
   bool AccountDrawdownExceeded(
      double equity,
      double balance,
      double limitPercent
   )
   {
      return false;
   }

   // Fixed basket-loss shutdown is disabled.
   // One losing position must not automatically close
   // other positions managed by this EA.
   bool BasketLossExceeded(
      double basketProfit,
      double maxLossCurrency
   )
   {
      return false;
   }
};

#endif
