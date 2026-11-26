#ifndef GOLD_EXIT_MANAGER
#define GOLD_EXIT_MANAGER
#include <Trade/Trade.mqh>
class CExitManager
{
public:
 bool CloseAll(CTrade &trade,string symbol,long magic)
 {
   bool allClosed=true;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);if(ticket==0)continue;
      if(PositionGetString(POSITION_SYMBOL)!=symbol || PositionGetInteger(POSITION_MAGIC)!=magic)continue;
      if(!trade.PositionClose(ticket))allClosed=false;
   }
   return allClosed;
 }
};
#endif
