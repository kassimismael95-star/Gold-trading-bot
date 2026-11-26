#ifndef GOLD_SESSION_FILTER
#define GOLD_SESSION_FILTER
class CSessionFilter
{
public:
 bool Allowed(bool enabled,int startHour,int endHour)
 {
   if(!enabled)return true;
   if(startHour<0 || startHour>23 || endHour<0 || endHour>24)return false;
   datetime serverTime=TimeTradeServer(); if(serverTime<=0)return false;
   MqlDateTime now; TimeToStruct(serverTime,now);
   if(startHour==endHour)return false;
   if(startHour<endHour)return now.hour>=startHour && now.hour<endHour;
   return now.hour>=startHour || now.hour<endHour;
 }
};
#endif
