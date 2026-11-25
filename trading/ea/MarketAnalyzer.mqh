#ifndef GOLD_MARKET_ANALYZER
#define GOLD_MARKET_ANALYZER
class CMarketAnalyzer
{
public:
 double ATR(string symbol,ENUM_TIMEFRAMES timeframe,int period)
 {
   if(period<2 || period>200)return 0.0;
   MqlRates rates[]; ArraySetAsSeries(rates,true);
   int copied=CopyRates(symbol,timeframe,1,period+1,rates);
   if(copied<period+1)return 0.0;
   double sum=0.0;
   for(int i=0;i<period;i++)
   {
      double highLow=rates[i].high-rates[i].low;
      double highClose=MathAbs(rates[i].high-rates[i+1].close);
      double lowClose=MathAbs(rates[i].low-rates[i+1].close);
      sum+=MathMax(highLow,MathMax(highClose,lowClose));
   }
   return sum/(double)period;
 }
 int Trend(string symbol,ENUM_TIMEFRAMES timeframe)
 {
   MqlRates rates[]; ArraySetAsSeries(rates,true);
   if(CopyRates(symbol,timeframe,1,25,rates)!=25)return 0;
   double fast=0.0,slow=0.0;
   for(int i=0;i<5;i++)fast+=rates[i].close;
   for(int i=5;i<25;i++)slow+=rates[i].close;
   fast/=5.0; slow/=20.0;
   if(fast>slow)return 1;
   if(fast<slow)return -1;
   return 0;
 }
};
#endif
