
#ifndef GOLD_MARKET_ANALYZER
#define GOLD_MARKET_ANALYZER

// Market information used exclusively by the post-entry supervisor.
struct SMarketState
{
   double atr;
   double averageRange;
   double volatilityRatio;
   double momentum;
   double previousMomentum;

   int trend;

   bool momentumStrengthening;
   bool momentumWeakening;
   bool dataValid;
};

class CMarketAnalyzer
{
private:

   bool ValidPrice(double value)
   {
      return value > 0.0 && value < DBL_MAX;
   }

   double AverageRange(
      MqlRates &rates[],
      int start,
      int count
   )
   {
      int available = ArraySize(rates);

      if(
         count <= 0 ||
         start < 0 ||
         start + count > available
      )
      {
         return 0.0;
      }

      double total = 0.0;

      for(int i = start; i < start + count; i++)
      {
         double range = rates[i].high - rates[i].low;

         if(range < 0.0)
            return 0.0;

         total += range;
      }

      return total / (double)count;
   }

   void ResetState(SMarketState &state)
   {
      state.atr = 0.0;
      state.averageRange = 0.0;
      state.volatilityRatio = 1.0;
      state.momentum = 0.0;
      state.previousMomentum = 0.0;

      state.trend = 0;

      state.momentumStrengthening = false;
      state.momentumWeakening = false;
      state.dataValid = false;
   }

public:

   // Average true range using completed candles only.
   double ATR(
      string symbol,
      ENUM_TIMEFRAMES timeframe,
      int period
   )
   {
      if(
         symbol == "" ||
         period < 2 ||
         period > 200
      )
      {
         return 0.0;
      }

      MqlRates rates[];
      ArraySetAsSeries(rates, true);

      int copied = CopyRates(
         symbol,
         timeframe,
         1,
         period + 1,
         rates
      );

      if(copied < period + 1)
         return 0.0;

      double total = 0.0;

      for(int i = 0; i < period; i++)
      {
         if(
            !ValidPrice(rates[i].high) ||
            !ValidPrice(rates[i].low) ||
            !ValidPrice(rates[i + 1].close)
         )
         {
            return 0.0;
         }

         double highLow =
            rates[i].high - rates[i].low;

         double highClose =
            MathAbs(
               rates[i].high - rates[i + 1].close
            );

         double lowClose =
            MathAbs(
               rates[i].low - rates[i + 1].close
            );

         double trueRange =
            MathMax(
               highLow,
               MathMax(highClose, lowClose)
            );

         if(trueRange < 0.0)
            return 0.0;

         total += trueRange;
      }

      return total / (double)period;
   }

   // Compare recent completed candles with older completed candles.
   // 1 = upward trend, -1 = downward trend, 0 = unclear.
   int Trend(
      string symbol,
      ENUM_TIMEFRAMES timeframe
   )
   {
      if(symbol == "")
         return 0;

      MqlRates rates[];
      ArraySetAsSeries(rates, true);

      if(
         CopyRates(
            symbol,
            timeframe,
            1,
            25,
            rates
         ) != 25
      )
      {
         return 0;
      }

      double fast = 0.0;
      double slow = 0.0;

      for(int i = 0; i < 5; i++)
      {
         if(!ValidPrice(rates[i].close))
            return 0;

         fast += rates[i].close;
      }

      for(int i = 5; i < 25; i++)
      {
         if(!ValidPrice(rates[i].close))
            return 0;

         slow += rates[i].close;
      }

      fast /= 5.0;
      slow /= 20.0;

      if(fast > slow)
         return 1;

      if(fast < slow)
         return -1;

      return 0;
   }

   // Build one consistent market snapshot.
   // Uses completed candles to avoid unstable current-candle readings.
   bool Analyze(
      string symbol,
      ENUM_TIMEFRAMES timeframe,
      SMarketState &state
   )
   {
      ResetState(state);

      if(symbol == "")
         return false;

      if(!SymbolSelect(symbol, true))
         return false;

      MqlRates rates[];
      ArraySetAsSeries(rates, true);

      int copied = CopyRates(
         symbol,
         timeframe,
         1,
         32,
         rates
      );

      if(copied < 32)
         return false;

      for(int i = 0; i < 9; i++)
      {
         if(
            !ValidPrice(rates[i].close) ||
            !ValidPrice(rates[i].high) ||
            !ValidPrice(rates[i].low)
         )
         {
            return false;
         }
      }

      // Volatility baseline.
      state.atr = ATR(
         symbol,
         timeframe,
         14
      );

      if(state.atr <= 0.0)
      {
         ResetState(state);
         return false;
      }

      // Compare recent range with the previous range.
      state.averageRange =
         AverageRange(rates, 1, 10);

      double recentRange =
         AverageRange(rates, 0, 5);

      double previousRange =
         AverageRange(rates, 5, 10);

      if(
         state.averageRange <= 0.0 ||
         recentRange <= 0.0
      )
      {
         ResetState(state);
         return false;
      }

      if(previousRange > 0.0)
      {
         state.volatilityRatio =
            recentRange / previousRange;
      }
      else
      {
         state.volatilityRatio = 1.0;
      }

      if(state.volatilityRatio <= 0.0)
         state.volatilityRatio = 1.0;

      // Recent completed-candle price movement.
      state.momentum =
         rates[0].close - rates[4].close;

      // Previous completed-candle movement.
      state.previousMomentum =
         rates[4].close - rates[8].close;

      state.trend = Trend(
         symbol,
         timeframe
      );

      double currentStrength =
         MathAbs(state.momentum);

      double previousStrength =
         MathAbs(state.previousMomentum);

      // Acceleration and weakening are descriptive signals.
      // They do not change the original entry strategy.
      state.momentumStrengthening =
         currentStrength > previousStrength &&
         currentStrength > 0.0;

      state.momentumWeakening =
         currentStrength < previousStrength;

      state.dataValid = true;

      return true;
   }

   // Signed momentum expressed in ATR units.
   // Positive = upward movement.
   // Negative = downward movement.
   double NormalizedMomentum(
      SMarketState &state
   )
   {
      if(
         !state.dataValid ||
         state.atr <= 0.0
      )
      {
         return 0.0;
      }

      return state.momentum / state.atr;
   }

   // Determine whether current market momentum supports
   // an already-open position.
   bool SupportsDirection(
      SMarketState &state,
      ENUM_POSITION_TYPE direction
   )
   {
      if(!state.dataValid)
         return false;

      double momentum =
         NormalizedMomentum(state);

      if(direction == POSITION_TYPE_BUY)
      {
         return
            momentum > 0.0 &&
            state.trend >= 0;
      }

      if(direction == POSITION_TYPE_SELL)
      {
         return
            momentum < 0.0 &&
            state.trend <= 0;
      }

      return false;
   }
};

#endif
