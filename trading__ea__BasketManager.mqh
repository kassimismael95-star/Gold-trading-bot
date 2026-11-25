#ifndef GOLD_BASKET_MANAGER
#define GOLD_BASKET_MANAGER
#include <Trade/Trade.mqh>
class CBasketManager
{
public:
 double Profit(string sym,long magic)
 {
   double total=0.0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i); if(ticket==0)continue;
      if(PositionGetString(POSITION_SYMBOL)==sym && PositionGetInteger(POSITION_MAGIC)==magic)
         total+=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP);
   }
   return total;
 }
};
#endif
