
#ifndef GOLD_EXECUTION_MANAGER
#define GOLD_EXECUTION_MANAGER

class CExecutionManager
{
private:
   int atrHandle;
   string atrSymbol;

public:
   CExecutionManager()
   {
      atrHandle = INVALID_HANDLE;
      atrSymbol = "";
   }

   void Init(string sym)
   {
      if(atrHandle != INVALID_HANDLE)
      {
         IndicatorRelease(atrHandle);
         atrHandle = INVALID_HANDLE;
      }

      atrSymbol = sym;
      atrHandle = iATR(sym, PERIOD_M1, 14);

      if(atrHandle == INVALID_HANDLE)
      {
         Print("ExecutionManager: failed to create ATR handle for ", sym);
      }
   }

   void Release()
   {
      if(atrHandle != INVALID_HANDLE)
      {
         IndicatorRelease(atrHandle);
         atrHandle = INVALID_HANDLE;
      }

      atrSymbol = "";
   }

   bool EntryCostOK(string sym, ENUM_ORDER_TYPE side, int confidence)
   {
      MqlTick tick;

      if(!SymbolInfoTick(sym, tick))
         return false;

      if(tick.ask <= 0.0 || tick.bid <= 0.0 || tick.ask < tick.bid)
         return false;

      if(atrHandle == INVALID_HANDLE || atrSymbol != sym)
         return false;

      double atrBuffer[];
      ArraySetAsSeries(atrBuffer, true);

      if(CopyBuffer(atrHandle, 0, 0, 1, atrBuffer) < 1)
         return false;

      double atr = atrBuffer[0];

      if(atr <= 0.0)
         return false;

      /*
         Estimate the available price movement from current volatility
         and signal confidence.

         Confidence 8+ : stronger expected movement
         Confidence 6+ : moderate expected movement
         Other signals: conservative expected movement
      */
      double movementFactor = 1.1;

      if(confidence >= 8)
         movementFactor = 1.8;
      else if(confidence >= 6)
         movementFactor = 1.4;

      double expectedMove = atr * movementFactor;

      if(expectedMove <= 0.0)
         return false;

      /*
         Dynamic spread evaluation:
         - No fixed pip spread ceiling.
         - No fixed spread-to-ATR percentage.
         - Compare the current spread with the movement expected
           from this particular market opportunity.
         - Reject only when the spread consumes the entire
           estimated movement or more.
      */
      double currentSpread = tick.ask - tick.bid;

      if(currentSpread >= expectedMove)
         return false;

      /*
         Confirm the selected direction is valid.
         The actual entry price is checked by the EA when it submits
         the order, so this method does not place or modify trades.
      */
      if(side != ORDER_TYPE_BUY && side != ORDER_TYPE_SELL)
         return false;

      return true;
   }
};

#endif
