
#ifndef GOLD_BASKET_MANAGER
#define GOLD_BASKET_MANAGER

class CBasketManager
{
public:

   // Calculate combined floating profit for this EA's positions.
   double Profit(string symbol, long magic)
   {
      double total = 0.0;

      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);

         if(ticket == 0)
            continue;

         if(!PositionSelectByTicket(ticket))
            continue;

         if(PositionGetString(POSITION_SYMBOL) != symbol)
            continue;

         if(PositionGetInteger(POSITION_MAGIC) != magic)
            continue;

         total += PositionGetDouble(POSITION_PROFIT);
         total += PositionGetDouble(POSITION_SWAP);
      }

      return total;
   }

   // Original equity-based basket profit targets.
   double TargetForEquity(double equity)
   {
      if(equity < 4.0)       return 0.35;
      if(equity < 10.0)      return 0.50;
      if(equity < 25.0)      return 1.00;
      if(equity < 50.0)      return 2.00;
      if(equity < 100.0)     return 4.00;
      if(equity < 250.0)     return 8.00;
      if(equity < 500.0)     return 15.00;
      if(equity < 1000.0)    return 30.00;
      if(equity < 2000.0)    return 60.00;
      if(equity < 5000.0)    return 120.00;
      if(equity < 10000.0)   return 250.00;
      if(equity < 25000.0)   return 600.00;

      return 1500.00;
   }

   bool TargetReached(double profit, double target)
   {
      return target > 0.0 && profit >= target;
   }

   // Check whether any matching positions remain open.
   bool HasOpenPositions(string symbol, long magic)
   {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);

         if(ticket == 0)
            continue;

         if(!PositionSelectByTicket(ticket))
            continue;

         if(PositionGetString(POSITION_SYMBOL) == symbol &&
            PositionGetInteger(POSITION_MAGIC) == magic)
         {
            return true;
         }
      }

      return false;
   }
};

#endif
