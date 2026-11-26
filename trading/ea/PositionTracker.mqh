
#ifndef GOLD_POSITION_TRACKER
#define GOLD_POSITION_TRACKER

class CPositionTracker
{
private:
   bool Matches(ulong ticket, string symbol, long magic)
   {
      if(ticket == 0)
         return false;

      if(!PositionSelectByTicket(ticket))
         return false;

      if(PositionGetString(POSITION_SYMBOL) != symbol)
         return false;

      if(PositionGetInteger(POSITION_MAGIC) != magic)
         return false;

      return true;
   }

public:

   // Count broker-confirmed positions for this symbol and EA magic number.
   int Count(string symbol, long magic)
   {
      int count = 0;

      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);

         if(Matches(ticket, symbol, magic))
            count++;
      }

      return count;
   }

   // Retrieve the ticket of a specific managed position by index.
   // Returns 0 when the requested index does not exist.
   ulong TicketAt(string symbol, long magic, int requestedIndex)
   {
      if(requestedIndex < 0)
         return 0;

      int currentIndex = 0;

      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);

         if(!Matches(ticket, symbol, magic))
            continue;

         if(currentIndex == requestedIndex)
            return ticket;

         currentIndex++;
      }

      return 0;
   }

   // Check whether a ticket belongs to this EA and symbol.
   bool IsManagedPosition(ulong ticket, string symbol, long magic)
   {
      return Matches(ticket, symbol, magic);
   }

   // Get the broker's stable position identifier.
   // Returns 0 if the position cannot be selected.
   ulong Identifier(ulong ticket)
   {
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         return 0;

      return (ulong)PositionGetInteger(POSITION_IDENTIFIER);
   }

   // Find the current ticket using a previously stored position identifier.
   // This helps recover position references after an EA restart.
   ulong FindTicketByIdentifier(
      ulong identifier,
      string symbol,
      long magic
   )
   {
      if(identifier == 0)
         return 0;

      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);

         if(!Matches(ticket, symbol, magic))
            continue;

         ulong currentIdentifier =
            (ulong)PositionGetInteger(POSITION_IDENTIFIER);

         if(currentIdentifier == identifier)
            return ticket;
      }

      return 0;
   }

   // Read the current volume of a managed position.
   double Volume(ulong ticket, string symbol, long magic)
   {
      if(!Matches(ticket, symbol, magic))
         return 0.0;

      return PositionGetDouble(POSITION_VOLUME);
   }

   // Read the current floating profit including swap.
   double FloatingProfit(ulong ticket, string symbol, long magic)
   {
      if(!Matches(ticket, symbol, magic))
         return 0.0;

      double profit = PositionGetDouble(POSITION_PROFIT);
      double swap   = PositionGetDouble(POSITION_SWAP);

      return profit + swap;
   }

   // Read the position's current direction.
   ENUM_POSITION_TYPE Direction(
      ulong ticket,
      string symbol,
      long magic
   )
   {
      if(!Matches(ticket, symbol, magic))
         return (ENUM_POSITION_TYPE)-1;

      return (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   }

   // Read the position's opening price.
   double OpenPrice(ulong ticket, string symbol, long magic)
   {
      if(!Matches(ticket, symbol, magic))
         return 0.0;

      return PositionGetDouble(POSITION_PRICE_OPEN);
   }

   // Read the current stop-loss.
   double StopLoss(ulong ticket, string symbol, long magic)
   {
      if(!Matches(ticket, symbol, magic))
         return 0.0;

      return PositionGetDouble(POSITION_SL);
   }

   // Read the current take-profit.
   double TakeProfit(ulong ticket, string symbol, long magic)
   {
      if(!Matches(ticket, symbol, magic))
         return 0.0;

      return PositionGetDouble(POSITION_TP);
   }
};

#endif
