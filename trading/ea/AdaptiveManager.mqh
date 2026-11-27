
#ifndef GOLD_ADAPTIVE_MANAGER
#define GOLD_ADAPTIVE_MANAGER

class CAdaptiveManager
{
private:
   long accountId;

   int winStreak;
   int lossStreak;
   int totalWins;
   int totalLosses;

   double totalWinningProfit;
   double totalLosingProfit;

   string Key(string suffix)
   {
      return "GoldAdaptive_" +
             (string)accountId + "_" + suffix;
   }

   void ResetStatistics()
   {
      winStreak = 0;
      lossStreak = 0;
      totalWins = 0;
      totalLosses = 0;

      totalWinningProfit = 0.0;
      totalLosingProfit = 0.0;
   }

   void Persist()
   {
      if(accountId <= 0)
         return;

      GlobalVariableSet(Key("wins"), (double)winStreak);
      GlobalVariableSet(Key("losses"), (double)lossStreak);

      GlobalVariableSet(Key("total_wins"), (double)totalWins);
      GlobalVariableSet(Key("total_losses"), (double)totalLosses);

      GlobalVariableSet(
         Key("winning_profit"),
         totalWinningProfit
      );

      GlobalVariableSet(
         Key("losing_profit"),
         totalLosingProfit
      );
   }

public:

   CAdaptiveManager()
   {
      accountId = 0;
      ResetStatistics();
   }

   void Init(long id)
   {
      accountId = id;

      ResetStatistics();

      if(accountId <= 0)
         return;

      if(GlobalVariableCheck(Key("wins")))
         winStreak = (int)GlobalVariableGet(Key("wins"));

      if(GlobalVariableCheck(Key("losses")))
         lossStreak = (int)GlobalVariableGet(Key("losses"));

      if(GlobalVariableCheck(Key("total_wins")))
         totalWins = (int)GlobalVariableGet(Key("total_wins"));

      if(GlobalVariableCheck(Key("total_losses")))
         totalLosses = (int)GlobalVariableGet(Key("total_losses"));

      if(GlobalVariableCheck(Key("winning_profit")))
      {
         totalWinningProfit =
            GlobalVariableGet(Key("winning_profit"));
      }

      if(GlobalVariableCheck(Key("losing_profit")))
      {
         totalLosingProfit =
            GlobalVariableGet(Key("losing_profit"));
      }
   }

   // Records each closing deal once.
   // Learning never changes entry decisions or lot sizing.
   void RecordOutcome(
      long id,
      ulong dealId,
      double pnl
   )
   {
      if(id != accountId || accountId <= 0)
         return;

      if(dealId == 0 || !MathIsValidNumber(pnl))
         return;

      string marker =
         "GoldAdaptiveDeal_" +
         (string)id + "_" +
         (string)dealId;

      // Prevent processing the same deal twice.
      if(GlobalVariableCheck(marker))
         return;

      // Claim this deal before updating statistics.
      GlobalVariableSet(marker, 1.0);

      if(pnl > 0.0)
      {
         winStreak++;
         lossStreak = 0;

         totalWins++;
         totalWinningProfit += pnl;
      }
      else if(pnl < 0.0)
      {
         lossStreak++;
         winStreak = 0;

         totalLosses++;
         totalLosingProfit += MathAbs(pnl);
      }

      Persist();
   }

   // Learning must never change the original lot size.
   double VolumeMultiplier()
   {
      return 1.0;
   }

   // No additional entry-confidence filter.
   int MinimumConfidence()
   {
      return 0;
   }

   int WinStreak()
   {
      return winStreak;
   }

   int LossStreak()
   {
      return lossStreak;
   }

   int TotalWins()
   {
      return totalWins;
   }

   int TotalLosses()
   {
      return totalLosses;
   }

   double TotalWinningProfit()
   {
      return totalWinningProfit;
   }

   double TotalLosingProfit()
   {
      return totalLosingProfit;
   }

   double NetRecordedProfit()
   {
      return totalWinningProfit - totalLosingProfit;
   }

   double WinRate()
   {
      int total = totalWins + totalLosses;

      if(total <= 0)
         return 0.0;

      return (
         (double)totalWins /
         (double)total
      ) * 100.0;
   }
};

#endif
