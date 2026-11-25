#ifndef GOLD_ENTRY_FILTER
#define GOLD_ENTRY_FILTER
#include "TrendDetector.mqh"
#include "VolatilityAnalyzer.mqh"
#include "SpreadAnalyzer.mqh"
#include "SignalConfirmation.mqh"
class CEntryFilter
{
private:
 CTrendDetector trend; CVolatilityAnalyzer volatility; CSpreadAnalyzer spread; CSignalConfirmation confirmation;
public:
 bool Allowed(string symbol,ENUM_ORDER_TYPE side,bool requireCandle)
 {
   if(!trend.Matches(symbol,side))return false;
   if(!volatility.IsValid(symbol,0.00002,0.02))return false;
   if(!spread.IsAcceptable(symbol,0.30))return false;
   if(requireCandle && !confirmation.Confirm(symbol,side))return false;
   return true;
 }
};
#endif
