
#ifndef GOLD_TRADE_RECOVERY
#define GOLD_TRADE_RECOVERY

#include <Trade/Trade.mqh>

// Original information captured when an entry is confirmed
// by the MT5 broker. Used only by post-entry management.
struct SOriginalEntryContext
{
   long accountId;
   ulong positionIdentifier;

   ENUM_ORDER_TYPE side;

   double entryPrice;
   double initialStopLoss;
   double initialTakeProfit;
   double initialVolume;

   int confidence;
   int signedScore;

   double shortDelta;
   double fullDelta;
   double candleDelta;
   double recentMovement;
   double candleOpen;

   datetime candleMinute;
   datetime recordedAt;

   bool valid;
};

class CTradeRecovery
{
private:

   string EntryBarKey(long accountId)
   {
      return "GoldLastEntryBar_" + (string)accountId;
   }

   string ContextPrefix(
      long accountId,
      ulong positionIdentifier
   )
   {
      return "GC_" +
             (string)accountId +
             "_" +
             (string)positionIdentifier +
             "_";
   }

   string ContextKey(
      long accountId,
      ulong positionIdentifier,
      string field
   )
   {
      return ContextPrefix(
         accountId,
         positionIdentifier
      ) + field;
   }

   bool HasContextField(
      long accountId,
      ulong positionIdentifier,
      string field
   )
   {
      return GlobalVariableCheck(
         ContextKey(
            accountId,
            positionIdentifier,
            field
         )
      );
   }

   bool SaveValue(
      long accountId,
      ulong positionIdentifier,
      string field,
      double value
   )
   {
      string key = ContextKey(
         accountId,
         positionIdentifier,
         field
      );

      datetime saved = GlobalVariableSet(key, value);

      return saved != 0;
   }

   double ReadValue(
      long accountId,
      ulong positionIdentifier,
      string field,
      double fallback = 0.0
   )
   {
      string key = ContextKey(
         accountId,
         positionIdentifier,
         field
      );

      if(!GlobalVariableCheck(key))
         return fallback;

      return GlobalVariableGet(key);
   }

public:

   // ---------------------------------------------------------
   // EXISTING RESTART DUPLICATE-ENTRY PROTECTION
   // ---------------------------------------------------------

   string GetEntryBarKey(long accountId)
   {
      return EntryBarKey(accountId);
   }

   datetime LastEntryBar(long accountId)
   {
      string key = EntryBarKey(accountId);

      if(!GlobalVariableCheck(key))
         return 0;

      return (datetime)GlobalVariableGet(key);
   }

   void RecordEntry(
      long accountId,
      datetime barTime
   )
   {
      if(accountId <= 0 || barTime <= 0)
         return;

      GlobalVariableSet(
         EntryBarKey(accountId),
         (double)barTime
      );
   }

   bool RestartDuplicateBlock(
      long accountId,
      datetime currentBar
   )
   {
      datetime previous = LastEntryBar(accountId);

      return (
         currentBar > 0 &&
         previous == currentBar
      );
   }

   // ---------------------------------------------------------
   // SAVE BROKER-CONFIRMED ORIGINAL ENTRY CONTEXT
   // ---------------------------------------------------------

   bool SaveEntryContext(
      long accountId,
      ulong positionIdentifier,
      ENUM_ORDER_TYPE side,
      double entryPrice,
      double initialStopLoss,
      double initialTakeProfit,
      double initialVolume,
      int confidence,
      int signedScore,
      double shortDelta,
      double fullDelta,
      double candleDelta,
      double recentMovement,
      double candleOpen,
      datetime candleMinute,
      datetime recordedAt
   )
   {
      if(accountId <= 0 || positionIdentifier == 0)
         return false;

      if(side != ORDER_TYPE_BUY &&
         side != ORDER_TYPE_SELL)
      {
         return false;
      }

      if(entryPrice <= 0.0 ||
         initialStopLoss <= 0.0 ||
         initialTakeProfit <= 0.0 ||
         initialVolume <= 0.0)
      {
         return false;
      }

      if(recordedAt <= 0)
         recordedAt = TimeCurrent();

      // Save each field independently. The final validity
      // marker is written only after every field succeeds.
      bool ok = true;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "side",
         (double)side
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "entry",
         entryPrice
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "sl",
         initialStopLoss
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "tp",
         initialTakeProfit
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "vol",
         initialVolume
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "conf",
         (double)confidence
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "score",
         (double)signedScore
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "short",
         shortDelta
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "full",
         fullDelta
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "candle",
         candleDelta
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "move",
         recentMovement
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "open",
         candleOpen
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "minute",
         (double)candleMinute
      ) && ok;

      ok = SaveValue(
         accountId,
         positionIdentifier,
         "time",
         (double)recordedAt
      ) && ok;

      if(!ok)
      {
         Print(
            "Entry context persistence failed. Account=",
            accountId,
            " Position identifier=",
            positionIdentifier
         );

         return false;
      }

      // Validity marker is deliberately written last.
      if(!SaveValue(
         accountId,
         positionIdentifier,
         "valid",
         1.0
      ))
      {
         Print(
            "Entry context validity marker could not be saved. ",
            "Position identifier=",
            positionIdentifier
         );

         return false;
      }

      Print(
         "Original entry context saved. Account=",
         accountId,
         " Position identifier=",
         positionIdentifier,
         " Side=",
         EnumToString(side),
         " Entry=",
         DoubleToString(entryPrice, 5)
      );

      return true;
   }

   // ---------------------------------------------------------
   // LOAD ORIGINAL ENTRY CONTEXT AFTER RESTART
   // ---------------------------------------------------------

   bool LoadEntryContext(
      long accountId,
      ulong positionIdentifier,
      SOriginalEntryContext &context
   )
   {
      context.accountId = accountId;
      context.positionIdentifier = positionIdentifier;

      context.side = ORDER_TYPE_BUY;

      context.entryPrice = 0.0;
      context.initialStopLoss = 0.0;
      context.initialTakeProfit = 0.0;
      context.initialVolume = 0.0;

      context.confidence = 0;
      context.signedScore = 0;

      context.shortDelta = 0.0;
      context.fullDelta = 0.0;
      context.candleDelta = 0.0;
      context.recentMovement = 0.0;
      context.candleOpen = 0.0;

      context.candleMinute = 0;
      context.recordedAt = 0;

      context.valid = false;

      if(accountId <= 0 || positionIdentifier == 0)
         return false;

      if(!HasContextField(
         accountId,
         positionIdentifier,
         "valid"
      ))
      {
         return false;
      }

      if(ReadValue(
         accountId,
         positionIdentifier,
         "valid"
      ) < 0.5)
      {
         return false;
      }

      // Refuse incomplete records rather than reconstructing
      // missing historical values from current market prices.
      string requiredFields[] =
      {
         "side",
         "entry",
         "sl",
         "tp",
         "vol",
         "conf",
         "score",
         "short",
         "full",
         "candle",
         "move",
         "open",
         "minute",
         "time"
      };

      for(int i = 0; i < ArraySize(requiredFields); i++)
      {
         if(!HasContextField(
            accountId,
            positionIdentifier,
            requiredFields[i]
         ))
         {
            return false;
         }
      }

      int storedSide = (int)ReadValue(
         accountId,
         positionIdentifier,
         "side"
      );

      if(storedSide != ORDER_TYPE_BUY &&
         storedSide != ORDER_TYPE_SELL)
      {
         return false;
      }

      context.side = (ENUM_ORDER_TYPE)storedSide;

      context.entryPrice = ReadValue(
         accountId,
         positionIdentifier,
         "entry"
      );

      context.initialStopLoss = ReadValue(
         accountId,
         positionIdentifier,
         "sl"
      );

      context.initialTakeProfit = ReadValue(
         accountId,
         positionIdentifier,
         "tp"
      );

      context.initialVolume = ReadValue(
         accountId,
         positionIdentifier,
         "vol"
      );

      context.confidence = (int)ReadValue(
         accountId,
         positionIdentifier,
         "conf"
      );

      context.signedScore = (int)ReadValue(
         accountId,
         positionIdentifier,
         "score"
      );

      context.shortDelta = ReadValue(
         accountId,
         positionIdentifier,
         "short"
      );

      context.fullDelta = ReadValue(
         accountId,
         positionIdentifier,
         "full"
      );

      context.candleDelta = ReadValue(
         accountId,
         positionIdentifier,
         "candle"
      );

      context.recentMovement = ReadValue(
         accountId,
         positionIdentifier,
         "move"
      );

      context.candleOpen = ReadValue(
         accountId,
         positionIdentifier,
         "open"
      );

      context.candleMinute = (datetime)ReadValue(
         accountId,
         positionIdentifier,
         "minute"
      );

      context.recordedAt = (datetime)ReadValue(
         accountId,
         positionIdentifier,
         "time"
      );

      if(context.entryPrice <= 0.0 ||
         context.initialStopLoss <= 0.0 ||
         context.initialTakeProfit <= 0.0 ||
         context.initialVolume <= 0.0)
      {
         return false;
      }

      context.valid = true;

      return true;
   }

   // ---------------------------------------------------------
   // CHECK WHETHER A POSITION HAS SAVED ENTRY CONTEXT
   // ---------------------------------------------------------

   bool HasEntryContext(
      long accountId,
      ulong positionIdentifier
   )
   {
      if(accountId <= 0 || positionIdentifier == 0)
         return false;

      if(!HasContextField(
         accountId,
         positionIdentifier,
         "valid"
      ))
      {
         return false;
      }

      return ReadValue(
         accountId,
         positionIdentifier,
         "valid"
      ) > 0.5;
   }
};

#endif
