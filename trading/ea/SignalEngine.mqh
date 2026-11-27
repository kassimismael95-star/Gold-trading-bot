
#ifndef GOLD_SIGNAL_ENGINE
#define GOLD_SIGNAL_ENGINE

// ============================================================
// GOLD SCALPER AI - ORIGINAL MICRO MOMENTUM ENGINE
// ============================================================
// The original entry calculation is preserved.
//
// Added read-only context accessors for the post-entry
// intelligence supervisor. These accessors do not filter,
// delay, modify or block entry signals.
// ============================================================

class CSignalEngine
{
private:
   double prices[20];

   int count;
   int next;

   double candle_open;
   datetime last_minute;

   // Most recently calculated signal context.
   int last_score;
   double last_short_delta;
   double last_full_delta;
   double last_candle_delta;
   double last_price;

   datetime CurrentUTCMinute()
   {
      datetime current_time = TimeGMT();

      MqlDateTime parts;
      TimeToStruct(current_time, parts);

      parts.sec = 0;

      return StructToTime(parts);
   }

   // Calculates the original score without changing its rules.
   int CalculateScore(
      double &short_delta,
      double &full_delta,
      double &candle_delta
   )
   {
      short_delta = 0.0;
      full_delta = 0.0;
      candle_delta = 0.0;

      if(count < 3)
         return 6;

      int newest_index = (next - 1 + 20) % 20;
      int third_index = (next - 3 + 20) % 20;
      int oldest_index = (next - count + 20) % 20;

      double latest = prices[newest_index];
      double third_price = prices[third_index];
      double oldest_price = prices[oldest_index];

      int score = 0;

      // Original short-term momentum calculation.
      short_delta = latest - third_price;

      if(short_delta > 0.05)
         score += 4;
      else if(short_delta < -0.05)
         score -= 4;
      else if(short_delta > 0.0)
         score += 2;
      else if(short_delta < 0.0)
         score -= 2;

      // Original overall recorded price movement.
      full_delta = latest - oldest_price;

      if(full_delta > 0.15)
         score += 3;
      else if(full_delta < -0.15)
         score -= 3;
      else if(full_delta > 0.0)
         score += 1;
      else if(full_delta < 0.0)
         score -= 1;

      // Original current UTC minute candle movement.
      candle_delta = latest - candle_open;

      if(candle_delta > 0.10)
         score += 3;
      else if(candle_delta < -0.10)
         score -= 3;
      else if(candle_delta > 0.0)
         score += 1;
      else if(candle_delta < 0.0)
         score -= 1;

      // Original score boundaries.
      score = (int)MathMax(-10, MathMin(10, score));

      return score;
   }

   void RefreshContext()
   {
      last_score = CalculateScore(
         last_short_delta,
         last_full_delta,
         last_candle_delta
      );

      if(count > 0)
      {
         int newest_index = (next - 1 + 20) % 20;
         last_price = prices[newest_index];
      }
      else
      {
         last_price = 0.0;
      }
   }

public:

   CSignalEngine()
   {
      count = 0;
      next = 0;

      candle_open = 0.0;
      last_minute = 0;

      last_score = 6;
      last_short_delta = 0.0;
      last_full_delta = 0.0;
      last_candle_delta = 0.0;
      last_price = 0.0;

      ArrayInitialize(prices, 0.0);
   }

   // Record incoming market price using the bid/ask midpoint.
   void Observe(double bid, double ask)
   {
      if(bid <= 0.0 || ask <= 0.0 || ask < bid)
         return;

      double price = (bid + ask) / 2.0;

      datetime current_minute = CurrentUTCMinute();

      if(last_minute != current_minute || candle_open <= 0.0)
      {
         candle_open = price;
         last_minute = current_minute;
      }

      prices[next] = price;

      next = (next + 1) % 20;

      if(count < 20)
         count++;

      RefreshContext();
   }

   // Original BUY/SELL decision.
   bool GetSignal(
      ENUM_ORDER_TYPE &side,
      int &confidence
   )
   {
      confidence = 0;

      if(count < 3)
      {
         side = ORDER_TYPE_BUY;
         confidence = 6;

         last_score = 6;

         return true;
      }

      RefreshContext();

      if(last_score >= 0)
         side = ORDER_TYPE_BUY;
      else
         side = ORDER_TYPE_SELL;

      confidence = (int)MathAbs(last_score);

      return true;
   }

   // Original recent movement calculation.
   double RecentMovement()
   {
      if(count < 3)
         return 0.0;

      int newest_index = (next - 1 + 20) % 20;
      int third_index = (next - 3 + 20) % 20;

      return MathAbs(
         prices[newest_index] - prices[third_index]
      );
   }

   // Original signed momentum score.
   int GetSignedMomentumScore()
   {
      if(count < 3)
         return 6;

      RefreshContext();

      return last_score;
   }

   // Number of recorded observations.
   int GetTickCount()
   {
      return count;
   }

   // Current UTC minute candle opening price.
   double GetCandleOpen()
   {
      return candle_open;
   }

   // Latest recorded midpoint price.
   double GetLastPrice()
   {
      if(count <= 0)
         return 0.0;

      int newest_index = (next - 1 + 20) % 20;

      return prices[newest_index];
   }

   // Original short-term movement: latest minus third-latest.
   double GetShortDelta()
   {
      RefreshContext();
      return last_short_delta;
   }

   // Original full-buffer movement: latest minus oldest.
   double GetFullDelta()
   {
      RefreshContext();
      return last_full_delta;
   }

   // Original minute candle movement.
   double GetCandleDelta()
   {
      RefreshContext();
      return last_candle_delta;
   }

   // Current signed score, including the original warm-up default.
   int GetCurrentScore()
   {
      RefreshContext();
      return last_score;
   }

   // UTC minute associated with the current candle reference.
   datetime GetCandleMinute()
   {
      return last_minute;
   }
};

#endif
