
#ifndef GOLD_MARKET_ANALYZER
#define GOLD_MARKET_ANALYZER

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

   double AverageRange(MqlRates &rates[], int start, int count)
   {
      double total = 0.0;
      int available = ArraySize(rates);

      if(count <= 0 || start < 0 || start + count > available)
         return 0.0;

      for(int i = start; i < start + count; i++)
         total += rates[i].high - rates[i].low;

      return total / (double)count;
   }

public:

   double ATR(
      string symbol,
      ENUM_TIMEFRAMES timeframe,
      int period
   )
   {
      if(period < 2 || period > 200)
         return 0.0;

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

      double sum = 0.0;

      for(int i = 0; i < period; i++)
      {
         double highLow = rates[i].high - rates[i].low;

         double highClose =
            MathAbs(rates[i].high - rates[i + 1].close);

         double lowClose =
            MathAbs(rates[i].low - rates[i + 1].close);

         double trueRange =
            MathMax(highLow, MathMax(highClose, lowClose));

         sum += trueRange;
      }

      return sum / (double)period;
   }

   int Trend(
      string symbol,
      ENUM_TIMEFRAMES timeframe
   )
   {
      MqlRates rates[];
      ArraySetAsSeries(rates, true);

      if(CopyRates(symbol, timeframe, 1, 25, rates) != 25)
         return 0;

      double fast = 0.0;
      double slow = 0.0;

      for(int i = 0; i < 5; i++)
         fast += rates[i].close;

      for(int i = 5; i < 25; i++)
         slow += rates[i].close;

      fast /= 5.0;
      slow /= 20.0;

      if(fast > slow)
         return 1;

      if(fast < slow)
         return -1;

      return 0;
   }

   // Produce a complete snapshot of current market conditions.
   bool Analyze(
      string symbol,
      ENUM_TIMEFRAMES timeframe,
      SMarketState &state
   )
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

      MqlRates rates[];
      ArraySetAsSeries(rates, true);

      // Use completed candles to avoid unstable partial-candle readings.
      int copied = CopyRates(
         symbol,
         timeframe,
         1,
         32,
         rates
      );

      if(copied < 32)
         return false;

      state.atr = ATR(symbol, timeframe, 14);

      if(state.atr <= 0.0)
         return false;

      state.averageRange = AverageRange(rates, 1, 10);

      double recentRange = AverageRange(rates, 0, 5);
      double previousRange = AverageRange(rates, 5, 10);

      if(previousRange > 0.0)
         state.volatilityRatio = recentRange / previousRange;

      // Compare recent price movement over two completed periods.
      state.momentum = rates[0].close - rates[4].close;
      state.previousMomentum = rates[4].close - rates[8].close;

      state.trend = Trend(symbol, timeframe);

      double currentStrength = MathAbs(state.momentum);
      double previousStrength = MathAbs(state.previousMomentum);

      state.momentumStrengthening =
         currentStrength > previousStrength &&
         currentStrength > 0.0;

      state.momentumWeakening =
         currentStrength < previousStrength;

      state.dataValid = true;

      return true;
   }

   // Signed momentum normalized by ATR.
   // Positive means upward movement; negative means downward movement.
   double NormalizedMomentum(SMarketState &state)
   {
      if(!state.dataValid || state.atr <= 0.0)
         return 0.0;

      return state.momentum / state.atr;
   }

   // Indicates whether market momentum supports the position direction.
   bool SupportsDirection(
      SMarketState &state,
      ENUM_POSITION_TYPE direction
   )
   {
      if(!state.dataValid)
         return false;

      double momentum = NormalizedMomentum(state);

      if(direction == POSITION_TYPE_BUY)
         return momentum > 0.0 && state.trend >= 0;

      if(direction == POSITION_TYPE_SELL)
         return momentum < 0.0 && state.trend <= 0;

      return false;
   }
};

#endif
