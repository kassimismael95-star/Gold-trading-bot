
#ifndef GOLD_SIGNAL_ENGINE
#define GOLD_SIGNAL_ENGINE

// ============================================================
// GOLD SCALPER AI - ORIGINAL MICRO MOMENTUM ENGINE
// ============================================================
// Restores the MicroMomentumTracker calculation from the
// original Python strategy.
//
// This module only calculates the entry signal.
// It does not add trend filters, spread filters, volatility
// filters, candle confirmation or additional entry restrictions.
// ============================================================

class CSignalEngine
{
private:

   double prices[20];

   int count;
   int next;

   double candle_open;
   datetime last_minute;

   // ---------------------------------------------------------
   // Get the current UTC minute.
   // ---------------------------------------------------------
   datetime CurrentUTCMinute()
   {
      datetime current_time = TimeGMT();

      MqlDateTime parts;
      TimeToStruct(current_time, parts);

      parts.sec = 0;

      return StructToTime(parts);
   }

public:

   // ---------------------------------------------------------
   // Constructor
   // ---------------------------------------------------------
   CSignalEngine()
   {
      count = 0;
      next = 0;

      candle_open = 0.0;
      last_minute = 0;

      ArrayInitialize(prices, 0.0);
   }

   // ---------------------------------------------------------
   // Record incoming market price.
   // Uses the midpoint of bid and ask, as in the EA.
   // ---------------------------------------------------------
   void Observe(double bid, double ask)
   {
      if(bid <= 0.0 || ask <= 0.0 || ask < bid)
         return;

      double price = (bid + ask) / 2.0;

      datetime current_minute = CurrentUTCMinute();

      // Establish a new UTC minute candle reference.
      if(last_minute != current_minute || candle_open <= 0.0)
      {
         candle_open = price;
         last_minute = current_minute;
      }

      // Store price in the 20-tick circular buffer.
      prices[next] = price;

      next = (next + 1) % 20;

      if(count < 20)
         count++;
   }

   // ---------------------------------------------------------
   // Calculate original Gold Scalper momentum.
   //
   // Original Python:
   //   short_delta = latest - ticks[-3]
   //   full_delta = latest - ticks[0]
   //   candle_delta = latest - candle_open
   //
   // Original score range: -10 to +10.
   // ---------------------------------------------------------
   bool GetSignal(
      ENUM_ORDER_TYPE &side,
      int &confidence
   )
   {
      confidence = 0;

      // Preserve original Python behaviour.
      if(count < 3)
      {
         side = ORDER_TYPE_BUY;
         confidence = 6;

         return true;
      }

      int newest_index = (next - 1 + 20) % 20;

      int third_index = (next - 3 + 20) % 20;

      int oldest_index = (next - count + 20) % 20;

      double latest = prices[newest_index];

      double third_price = prices[third_index];

      double oldest_price = prices[oldest_index];

      int score = 0;

      // ------------------------------------------------------
      // 1. SHORT-TERM MOMENTUM
      // ------------------------------------------------------

      double short_delta = latest - third_price;

      if(short_delta > 0.05)
         score += 4;

      else if(short_delta < -0.05)
         score -= 4;

      else if(short_delta > 0.0)
         score += 2;

      else if(short_delta < 0.0)
         score -= 2;

      // ------------------------------------------------------
      // 2. OVERALL RECORDED PRICE MOVEMENT
      // ------------------------------------------------------

      double full_delta = latest - oldest_price;

      if(full_delta > 0.15)
         score += 3;

      else if(full_delta < -0.15)
         score -= 3;

      else if(full_delta > 0.0)
         score += 1;

      else if(full_delta < 0.0)
         score -= 1;

      // ------------------------------------------------------
      // 3. CURRENT UTC MINUTE CANDLE MOVEMENT
      // ------------------------------------------------------

      double candle_delta = latest - candle_open;

      if(candle_delta > 0.10)
         score += 3;

      else if(candle_delta < -0.10)
         score -= 3;

      else if(candle_delta > 0.0)
         score += 1;

      else if(candle_delta < 0.0)
         score -= 1;

      // ------------------------------------------------------
      // 4. ORIGINAL SCORE LIMIT
      // ------------------------------------------------------

      score = (int)MathMax(-10, MathMin(10, score));

      // ------------------------------------------------------
      // 5. ORIGINAL DIRECTION DECISION
      // ------------------------------------------------------

      if(score >= 0)
         side = ORDER_TYPE_BUY;

      else
         side = ORDER_TYPE_SELL;

      // The existing EA expects a positive confidence value.
      // Preserve the original score magnitude.
      confidence = (int)MathAbs(score);

      return true;
   }

   // ---------------------------------------------------------
   // Original recent movement calculation.
   // ---------------------------------------------------------
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

   // ---------------------------------------------------------
   // Access original signed momentum score.
   // Useful for intelligence modules.
   // ---------------------------------------------------------
   int GetSignedMomentumScore()
   {
      if(count < 3)
         return 6;

      ENUM_ORDER_TYPE side;

      int confidence = 0;

      if(!GetSignal(side, confidence))
         return 0;

      if(side == ORDER_TYPE_BUY)
         return confidence;

      return -confidence;
   }

   // ---------------------------------------------------------
   // Number of recorded observations.
   // ---------------------------------------------------------
   int GetTickCount()
   {
      return count;
   }

   // ---------------------------------------------------------
   // Current minute candle opening price.
   // ---------------------------------------------------------
   double GetCandleOpen()
   {
      return candle_open;
   }
};

#endif
