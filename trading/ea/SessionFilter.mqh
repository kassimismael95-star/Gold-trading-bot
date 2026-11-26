
#ifndef GOLD_SESSION_FILTER
#define GOLD_SESSION_FILTER

class CSessionFilter
{
public:

   // Compatibility with the existing GoldScalperEA.mq5 call.
   // Session settings must not reject original strategy signals.
   bool Allowed(
      bool enabled,
      int startHour,
      int endHour
   )
   {
      return true;
   }
};

#endif
