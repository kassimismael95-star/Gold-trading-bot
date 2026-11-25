#ifndef GOLD_NEWS_FILTER
#define GOLD_NEWS_FILTER
class CNewsFilter
{
public:
 bool IsBlocked(bool enabled,string currency,int minutesBefore,int minutesAfter)
 {
   if(!enabled)return false;
   datetime now=TimeTradeServer();
   if(now<=0)return true; // fail closed if calendar time is unavailable
   MqlCalendarValue values[];
   datetime from=now-(datetime)MathMax(0,minutesBefore)*60;
   datetime to=now+(datetime)MathMax(0,minutesAfter)*60;
   int count=CalendarValueHistory(values,from,to,NULL,currency);
   if(count<0)return true; // do not enter when enabled but calendar data failed
   for(int i=0;i<count;i++)
   {
      MqlCalendarEvent event;
      if(!CalendarEventById(values[i].event_id,event))continue;
      if(event.importance==CALENDAR_IMPORTANCE_HIGH)return true;
   }
   return false;
 }
};
#endif
