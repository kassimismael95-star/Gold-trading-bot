
#ifndef GOLD_EXECUTION_MANAGER
#define GOLD_EXECUTION_MANAGER

class CExecutionManager
{
private:

   bool ValidSide(ENUM_ORDER_TYPE side)
   {
      return (
         side == ORDER_TYPE_BUY ||
         side == ORDER_TYPE_SELL
      );
   }

public:

   CExecutionManager()
   {
   }

   void Init(string symbol)
   {
      // Symbol and broker configuration remain handled
      // by BrokerSpecification.mqh.
   }

   void Release()
   {
   }

   // Validate that a usable broker quote is available.
   bool QuoteAvailable(string symbol)
   {
      if(symbol == "")
         return false;

      MqlTick tick;

      if(!SymbolInfoTick(symbol, tick))
         return false;

      if(tick.bid <= 0.0 || tick.ask <= 0.0)
         return false;

      if(tick.ask < tick.bid)
         return false;

      if(tick.time <= 0)
         return false;

      return true;
   }

   // Preserve the original entry-cost behavior.
   // No arbitrary spread ceiling.
   // No confidence-based entry rejection.
   bool EntryCostOK(
      string symbol,
      ENUM_ORDER_TYPE side,
      int confidence
   )
   {
      if(!ValidSide(side))
         return false;

      if(!QuoteAvailable(symbol))
         return false;

      // Confidence remains available to the original
      // strategy but is not used as a new entry filter.

      return true;
   }
};

#endif
