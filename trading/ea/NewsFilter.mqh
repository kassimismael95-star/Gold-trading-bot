
#ifndef GOLD_NEWS_FILTER
#define GOLD_NEWS_FILTER

class CNewsFilter
{
public:

   // Keep the existing interface for GoldScalperEA.mq5.
   // Economic calendar events must not block original strategy signals.
   bool IsBlocked(
      bool enabled,
      string currency,
      int minutesBefore,
      int minutesAfter
   )
   {
      return false;
   }
};

#endif
