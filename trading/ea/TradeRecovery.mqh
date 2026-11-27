
#ifndef GOLD_TRADE_RECOVERY
#define GOLD_TRADE_RECOVERY

#include <Trade/Trade.mqh>

// Original information captured after broker-confirmed entry.
// Used exclusively by post-entry trade management.
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

   // Additional recovery metadata.
   bool historyRecovered;
   bool signalContextAvailable;
   double currentHistoryVolume;
   int historyDealCount;
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

   void ResetContext(
      SOriginalEntryContext &context,
      long accountId,
      ulong positionIdentifier
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

      context.historyRecovered = false;
      context.signalContextAvailable = false;
      context.currentHistoryVolume = 0.0;
      context.historyDealCount = 0;
   }

   bool SamePrice(double a, double b)
   {
      double tolerance = MathMax(
         0.0000001,
         MathMax(MathAbs(a), MathAbs(b)) * 0.0000001
      );

      return MathAbs(a - b) <= tolerance;
   }

   // ---------------------------------------------------------
   // HISTORY RECOVERY ENGINE
   // ---------------------------------------------------------

   bool BuildHistoryContext(
      long accountId,
      ulong positionIdentifier,
      long expectedMagic,
      string expectedSymbol,
      SOriginalEntryContext &context
   )
   {
      ResetContext(
         context,
         accountId,
         positionIdentifier
      );

      if(accountId <= 0 ||
         positionIdentifier == 0 ||
         expectedMagic <= 0 ||
         expectedSymbol == "")
      {
         return false;
      }

      ResetLastError();

      if(!HistorySelectByPosition(positionIdentifier))
      {
         Print(
            "Trade recovery: history selection failed. Position=",
            positionIdentifier,
            " Error=",
            GetLastError()
         );

         return false;
      }

      int total = HistoryDealsTotal();

      if(total <= 0)
         return false;

      ulong tickets[];
      long times[];

      ArrayResize(tickets, total);
      ArrayResize(times, total);

      int validDeals = 0;

      // Collect relevant trade deals.
      for(int i = 0; i < total; i++)
      {
         ulong ticket = HistoryDealGetTicket(i);

         if(ticket == 0)
            continue;

         ENUM_DEAL_TYPE dealType =
            (ENUM_DEAL_TYPE)HistoryDealGetInteger(
               ticket,
               DEAL_TYPE
            );

         if(dealType != DEAL_TYPE_BUY &&
            dealType != DEAL_TYPE_SELL)
         {
            continue;
         }

         long dealMagic = HistoryDealGetInteger(
            ticket,
            DEAL_MAGIC
         );

         string dealSymbol = HistoryDealGetString(
            ticket,
            DEAL_SYMBOL
         );

         // Strict ownership check.
         // Never merge manual trades or another EA's trades.
         if(dealMagic != expectedMagic)
         {
            Print(
               "Trade recovery refused: mixed magic number. ",
               "Position=",
               positionIdentifier
            );

            return false;
         }

         if(dealSymbol != expectedSymbol)
         {
            Print(
               "Trade recovery refused: mixed symbol. ",
               "Position=",
               positionIdentifier
            );

            return false;
         }

         tickets[validDeals] = ticket;

         times[validDeals] = HistoryDealGetInteger(
            ticket,
            DEAL_TIME_MSC
         );

         validDeals++;
      }

      if(validDeals <= 0)
         return false;

      ArrayResize(tickets, validDeals);
      ArrayResize(times, validDeals);

      // Sort chronologically.
      for(int i = 0; i < validDeals - 1; i++)
      {
         for(int j = i + 1; j < validDeals; j++)
         {
            if(times[j] < times[i])
            {
               long tempTime = times[i];
               times[i] = times[j];
               times[j] = tempTime;

               ulong tempTicket = tickets[i];
               tickets[i] = tickets[j];
               tickets[j] = tempTicket;
            }
         }
      }

      double currentVolume = 0.0;
      double weightedEntry = 0.0;

      double lifecycleInitialVolume = 0.0;

      double initialSL = 0.0;
      double initialTP = 0.0;

      ENUM_ORDER_TYPE currentSide = ORDER_TYPE_BUY;

      bool lifecycleActive = false;
      bool lifecycleContextValid = false;

      datetime lifecycleStart = 0;

      double volumeTolerance = 0.0000001;

      // Process every deal in chronological order.
      for(int i = 0; i < validDeals; i++)
      {
         ulong ticket = tickets[i];

         ENUM_DEAL_TYPE dealType =
            (ENUM_DEAL_TYPE)HistoryDealGetInteger(
               ticket,
               DEAL_TYPE
            );

         ENUM_DEAL_ENTRY dealEntry =
            (ENUM_DEAL_ENTRY)HistoryDealGetInteger(
               ticket,
               DEAL_ENTRY
            );

         double dealVolume = HistoryDealGetDouble(
            ticket,
            DEAL_VOLUME
         );

         double dealPrice = HistoryDealGetDouble(
            ticket,
            DEAL_PRICE
         );

         datetime dealTime =
            (datetime)HistoryDealGetInteger(
               ticket,
               DEAL_TIME
            );

         double dealSL = HistoryDealGetDouble(
            ticket,
            DEAL_SL
         );

         double dealTP = HistoryDealGetDouble(
            ticket,
            DEAL_TP
         );

         if(dealVolume <= 0.0 || dealPrice <= 0.0)
            return false;

         ENUM_ORDER_TYPE dealSide =
            (dealType == DEAL_TYPE_BUY)
            ? ORDER_TYPE_BUY
            : ORDER_TYPE_SELL;

         // --------------------------------------------------
         // NORMAL ENTRY
         // --------------------------------------------------

         if(dealEntry == DEAL_ENTRY_IN)
         {
            if(!lifecycleActive ||
               currentVolume <= volumeTolerance)
            {
               currentSide = dealSide;

               currentVolume = dealVolume;
               weightedEntry = dealPrice * dealVolume;

               lifecycleInitialVolume = dealVolume;

               initialSL = dealSL;
               initialTP = dealTP;

               lifecycleStart = dealTime;

               lifecycleActive = true;
               lifecycleContextValid =
                  (initialSL > 0.0 && initialTP > 0.0);

               continue;
            }

            // Same-direction addition.
            if(dealSide != currentSide)
            {
               Print(
                  "Trade recovery refused: unexpected opposite ",
                  "entry without reversal marker. Position=",
                  positionIdentifier
               );

               return false;
            }

            // All entry layers must have compatible original
            // protection levels for one combined context.
            if(!SamePrice(dealSL, initialSL) ||
               !SamePrice(dealTP, initialTP))
            {
               lifecycleContextValid = false;
            }

            weightedEntry += dealPrice * dealVolume;

            currentVolume += dealVolume;

            lifecycleInitialVolume += dealVolume;

            continue;
         }

         // --------------------------------------------------
         // NETTING REVERSAL
         // --------------------------------------------------

         if(dealEntry == DEAL_ENTRY_INOUT)
         {
            if(!lifecycleActive ||
               currentVolume <= volumeTolerance ||
               dealSide == currentSide)
            {
               Print(
                  "Trade recovery refused: ambiguous reversal. ",
                  "Position=",
                  positionIdentifier
               );

               return false;
            }

            double remainingVolume =
               dealVolume - currentVolume;

            if(remainingVolume <= volumeTolerance)
            {
               Print(
                  "Trade recovery refused: reversal volume ",
                  "cannot be reconstructed. Position=",
                  positionIdentifier
               );

               return false;
            }

            // The reversal creates a new directional lifecycle.
            currentSide = dealSide;

            currentVolume = remainingVolume;

            weightedEntry = dealPrice * remainingVolume;

            lifecycleInitialVolume = remainingVolume;

            initialSL = dealSL;
            initialTP = dealTP;

            lifecycleStart = dealTime;

            lifecycleActive = true;

            lifecycleContextValid =
               (initialSL > 0.0 && initialTP > 0.0);

            continue;
         }

         // --------------------------------------------------
         // NORMAL EXIT / CLOSE BY
         // --------------------------------------------------

         if(dealEntry == DEAL_ENTRY_OUT ||
            dealEntry == DEAL_ENTRY_OUT_BY)
         {
            if(!lifecycleActive ||
               currentVolume <= volumeTolerance)
            {
               Print(
                  "Trade recovery refused: exit without ",
                  "known opening history. Position=",
                  positionIdentifier
               );

               return false;
            }

            // Closing deal must be opposite to the open side.
            if(dealSide == currentSide)
            {
               Print(
                  "Trade recovery refused: inconsistent exit side. ",
                  "Position=",
                  positionIdentifier
               );

               return false;
            }

            if(dealVolume > currentVolume + volumeTolerance)
            {
               Print(
                  "Trade recovery refused: exit exceeds current ",
                  "volume without reversal marker. Position=",
                  positionIdentifier
               );

               return false;
            }

            currentVolume -= dealVolume;

            if(currentVolume <= volumeTolerance)
            {
               currentVolume = 0.0;
               weightedEntry = 0.0;

               lifecycleInitialVolume = 0.0;

               initialSL = 0.0;
               initialTP = 0.0;

               lifecycleStart = 0;

               lifecycleActive = false;
               lifecycleContextValid = false;
            }

            continue;
         }

         // Unknown deal-entry type: fail closed.
         Print(
            "Trade recovery refused: unsupported deal entry type. ",
            "Position=",
            positionIdentifier
         );

         return false;
      }

      // The history must describe a currently open lifecycle.
      if(!lifecycleActive ||
         currentVolume <= volumeTolerance ||
         lifecycleInitialVolume <= 0.0 ||
         weightedEntry <= 0.0 ||
         !lifecycleContextValid ||
         initialSL <= 0.0 ||
         initialTP <= 0.0 ||
         lifecycleStart <= 0)
      {
         return false;
      }

      double averageEntry =
         weightedEntry / lifecycleInitialVolume;

      if(averageEntry <= 0.0)
         return false;

      context.accountId = accountId;

      context.positionIdentifier = positionIdentifier;

      context.side = currentSide;

      context.entryPrice = averageEntry;

      context.initialStopLoss = initialSL;

      context.initialTakeProfit = initialTP;

      context.initialVolume = lifecycleInitialVolume;

      // Historical deal records cannot recreate the original
      // signal engine's confidence and tick/candle calculations.
      // Keep these values neutral instead of inventing them.
      context.confidence = 0;
      context.signedScore = 0;

      context.shortDelta = 0.0;
      context.fullDelta = 0.0;
      context.candleDelta = 0.0;
      context.recentMovement = 0.0;
      context.candleOpen = 0.0;

      context.candleMinute = 0;

      context.recordedAt = lifecycleStart;

      context.valid = true;

      context.historyRecovered = true;

      context.signalContextAvailable = false;

      context.currentHistoryVolume = currentVolume;

      context.historyDealCount = validDeals;

      return true;
   }

public:

   // ---------------------------------------------------------
   // RESTART DUPLICATE-ENTRY PROTECTION
   // ---------------------------------------------------------

   string GetEntryBarKey(long accountId)
   {
      return EntryBarKey(accountId);
   }

   datetime LastEntryBar(long accountId)
   {
      if(accountId <= 0)
         return 0;

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

      GlobalVariableFlush();
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

      // Invalidate old record before updating.
      if(!SaveValue(
         accountId,
         positionIdentifier,
         "valid",
         0.0
      ))
      {
         Print(
            "Could not invalidate old entry context. Account=",
            accountId,
            " Position=",
            positionIdentifier
         );

         return false;
      }

      GlobalVariableFlush();

      bool ok = true;

      ok = SaveValue(
         accountId, positionIdentifier,
         "side", (double)side
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "entry", entryPrice
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "sl", initialStopLoss
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "tp", initialTakeProfit
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "vol", initialVolume
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "conf", (double)confidence
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "score", (double)signedScore
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "short", shortDelta
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "full", fullDelta
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "candle", candleDelta
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "move", recentMovement
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "open", candleOpen
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "minute", (double)candleMinute
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "time", (double)recordedAt
      ) && ok;

      // Normal EA-saved context has signal information.
      ok = SaveValue(
         accountId, positionIdentifier,
         "recovered", 0.0
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "signal", 1.0
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "currentvol", initialVolume
      ) && ok;

      ok = SaveValue(
         accountId, positionIdentifier,
         "deals", 0.0
      ) && ok;

      if(!ok)
      {
         GlobalVariableFlush();

         Print(
            "Entry context persistence failed. Account=",
            accountId,
            " Position identifier=",
            positionIdentifier
         );

         return false;
      }

      GlobalVariableFlush();

      // Publish valid marker only after all fields are saved.
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

      GlobalVariableFlush();

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
      ResetContext(
         context,
         accountId,
         positionIdentifier
      );

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
         accountId, positionIdentifier, "entry"
      );

      context.initialStopLoss = ReadValue(
         accountId, positionIdentifier, "sl"
      );

      context.initialTakeProfit = ReadValue(
         accountId, positionIdentifier, "tp"
      );

      context.initialVolume = ReadValue(
         accountId, positionIdentifier, "vol"
      );

      context.confidence = (int)ReadValue(
         accountId, positionIdentifier, "conf"
      );

      context.signedScore = (int)ReadValue(
         accountId, positionIdentifier, "score"
      );

      context.shortDelta = ReadValue(
         accountId, positionIdentifier, "short"
      );

      context.fullDelta = ReadValue(
         accountId, positionIdentifier, "full"
      );

      context.candleDelta = ReadValue(
         accountId, positionIdentifier, "candle"
      );

      context.recentMovement = ReadValue(
         accountId, positionIdentifier, "move"
      );

      context.candleOpen = ReadValue(
         accountId, positionIdentifier, "open"
      );

      context.candleMinute = (datetime)ReadValue(
         accountId, positionIdentifier, "minute"
      );

      context.recordedAt = (datetime)ReadValue(
         accountId, positionIdentifier, "time"
      );

      // Optional metadata maintains compatibility with older records.
      context.historyRecovered =
         (ReadValue(
            accountId,
            positionIdentifier,
            "recovered",
            0.0
         ) >= 0.5);

      context.signalContextAvailable =
         (ReadValue(
            accountId,
            positionIdentifier,
            "signal",
            1.0
         ) >= 0.5);

      context.currentHistoryVolume = ReadValue(
         accountId,
         positionIdentifier,
         "currentvol",
         context.initialVolume
      );

      context.historyDealCount = (int)ReadValue(
         accountId,
         positionIdentifier,
         "deals",
         0.0
      );

      if(context.entryPrice <= 0.0 ||
         context.initialStopLoss <= 0.0 ||
         context.initialTakeProfit <= 0.0 ||
         context.initialVolume <= 0.0 ||
         context.recordedAt <= 0)
      {
         ResetContext(
            context,
            accountId,
            positionIdentifier
         );

         return false;
      }

      context.valid = true;

      return true;
   }

   // ---------------------------------------------------------
   // RECOVER MISSING CONTEXT FROM BROKER HISTORY
   // ---------------------------------------------------------

   bool RecoverEntryContextFromHistory(
      long accountId,
      ulong positionIdentifier,
      long expectedMagic,
      string expectedSymbol,
      SOriginalEntryContext &context
   )
   {
      ResetContext(
         context,
         accountId,
         positionIdentifier
      );

      // Existing complete context always takes priority.
      if(LoadEntryContext(
         accountId,
         positionIdentifier,
         context
      ))
      {
         return true;
      }

      SOriginalEntryContext recovered;

      if(!BuildHistoryContext(
         accountId,
         positionIdentifier,
         expectedMagic,
         expectedSymbol,
         recovered
      ))
      {
         Print(
            "Trade recovery could not safely reconstruct context. ",
            "Position=",
            positionIdentifier
         );

         return false;
      }

      // Persist recovered history.
      // Signal fields remain neutral because deal history
      // cannot recreate the original tick/candle signal.
      if(!SaveEntryContext(
         recovered.accountId,
         recovered.positionIdentifier,
         recovered.side,
         recovered.entryPrice,
         recovered.initialStopLoss,
         recovered.initialTakeProfit,
         recovered.initialVolume,
         0,
         0,
         0.0,
         0.0,
         0.0,
         0.0,
         0.0,
         0,
         recovered.recordedAt
      ))
      {
         return false;
      }

      bool metadataSaved = true;

      metadataSaved = SaveValue(
         accountId,
         positionIdentifier,
         "recovered",
         1.0
      ) && metadataSaved;

      metadataSaved = SaveValue(
         accountId,
         positionIdentifier,
         "signal",
         0.0
      ) && metadataSaved;

      metadataSaved = SaveValue(
         accountId,
         positionIdentifier,
         "currentvol",
         recovered.currentHistoryVolume
      ) && metadataSaved;

      metadataSaved = SaveValue(
         accountId,
         positionIdentifier,
         "deals",
         (double)recovered.historyDealCount
      ) && metadataSaved;

      GlobalVariableFlush();

      if(!metadataSaved)
      {
         Print(
            "Recovered context metadata could not be saved. ",
            "Position=",
            positionIdentifier
         );

         return false;
      }

      if(!LoadEntryContext(
         accountId,
         positionIdentifier,
         context
      ))
      {
         return false;
      }

      Print(
         "Position context recovered from broker history. ",
         "Position=",
         positionIdentifier,
         " Side=",
         EnumToString(context.side),
         " Entry=",
         DoubleToString(context.entryPrice, 5),
         " Initial volume=",
         DoubleToString(context.initialVolume, 2),
         " Current history volume=",
         DoubleToString(context.currentHistoryVolume, 2),
         " Deals=",
         context.historyDealCount,
         " Signal context unavailable"
      );

      return true;
   }

   // ---------------------------------------------------------
   // CHECK WHETHER A COMPLETE ENTRY CONTEXT EXISTS
   // ---------------------------------------------------------

   bool HasEntryContext(
      long accountId,
      ulong positionIdentifier
   )
   {
      SOriginalEntryContext context;

      return LoadEntryContext(
         accountId,
         positionIdentifier,
         context
      );
   }
};

#endif
