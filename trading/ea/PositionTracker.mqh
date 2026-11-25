#ifndef GOLD_POSITION_TRACKER
#define GOLD_POSITION_TRACKER
class CPositionTracker
{
public:
 int Count(string symbol,long magic)
 {
   int count=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   { ulong ticket=PositionGetTicket(i); if(ticket>0 && PositionGetString(POSITION_SYMBOL)==symbol && PositionGetInteger(POSITION_MAGIC)==magic)count++; }
   return count;
 }
};
#endif
