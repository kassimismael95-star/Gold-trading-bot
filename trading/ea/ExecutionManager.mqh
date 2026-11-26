
#ifndef GOLD_EXECUTION_MANAGER
#define GOLD_EXECUTION_MANAGER

class CExecutionManager
{
public:
   CExecutionManager()
   {
   }

   void Init(string sym)
   {
      // No fixed spread threshold or ATR rejection rule.
      // The symbol is selected and validated by the main EA.
   }

   void Release()
   {
   }

   bool EntryCostOK(string sym, ENUM_ORDER_TYPE side, int confidence)
   {
      MqlTick tick;

      // Reject only invalid market data or an invalid order direction.
      if(!SymbolInfoTick(sym, tick))
         return false;

      if(tick.bid <= 0.0 || tick.ask <= 0.0)
         return false;

      if(tick.ask < tick.bid)
         return false;

      if(side != ORDER_TYPE_BUY && side != ORDER_TYPE_SELL)
         return false;

      /*
         The original fixed spread/expected-move ratio has been removed.

         This function does not reject a valid entry because of:
         - a fixed spread-pip limit
         - a fixed spread-to-ATR ratio
         - an invented confidence multiplier
         - an arbitrary spread percentage

         Actual order volume, broker specifications, available margin,
         and the strategy's own signal and risk logic are checked by
         the existing EA before order submission.
      */

      return true;
   }
};

#endif
