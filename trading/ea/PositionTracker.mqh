
#ifndef GOLD_POSITION_TRACKER
#define GOLD_POSITION_TRACKER

// ============================================================
// GOLD SCALPER AI - BROKER POSITION TRACKER
// ============================================================
// MT5 broker state is authoritative.
// This class never opens, modifies or closes trades.
// ============================================================

struct SManagedPositionSnapshot
{
   ulong ticket;
   ulong identifier;

   string symbol;
   string comment;

   long magic;
   long openTime;

   ENUM_POSITION_TYPE direction;

   double openPrice;
   double currentPrice;

   double stopLoss;
   double takeProfit;

   double currentVolume;

   // Includes floating profit and swap.
   double floatingProfit;

   // Kept separately for reporting and reconciliation.
   double swap;

   bool valid;
};

class CPositionTracker
{
private:

   bool Matches(
      ulong ticket,
      string symbol,
      long magic
   )
   {
      if(ticket == 0 || symbol == "")
         return false;

      if(!PositionSelectByTicket(ticket))
         return false;

      if(PositionGetString(POSITION_SYMBOL) != symbol)
         return false;

      if(PositionGetInteger(POSITION_MAGIC) != magic)
         return false;

      return true;
   }

   void ResetSnapshot(
      SManagedPositionSnapshot &snapshot
   )
   {
      snapshot.ticket = 0;
      snapshot.identifier = 0;

      snapshot.symbol = "";
      snapshot.comment = "";

      snapshot.magic = 0;
      snapshot.openTime = 0;

      snapshot.direction = (ENUM_POSITION_TYPE)-1;

      snapshot.openPrice = 0.0;
      snapshot.currentPrice = 0.0;

      snapshot.stopLoss = 0.0;
      snapshot.takeProfit = 0.0;

      snapshot.currentVolume = 0.0;
      snapshot.floatingProfit = 0.0;
      snapshot.swap = 0.0;

      snapshot.valid = false;
   }

public:

   // Count broker-confirmed positions.
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

   // Retrieve a managed ticket by index.
   ulong TicketAt(
      string symbol,
      long magic,
      int requestedIndex
   )
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

   // Verify EA ownership.
   bool IsManagedPosition(
      ulong ticket,
      string symbol,
      long magic
   )
   {
      return Matches(ticket, symbol, magic);
   }

   // Read stable broker position identifier.
   ulong Identifier(ulong ticket)
   {
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         return 0;

      return (ulong)PositionGetInteger(
         POSITION_IDENTIFIER
      );
   }

   // Find a position using its stable identifier.
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
            (ulong)PositionGetInteger(
               POSITION_IDENTIFIER
            );

         if(currentIdentifier == identifier)
            return ticket;
      }

      return 0;
   }

   // Read current position volume.
   double Volume(
      ulong ticket,
      string symbol,
      long magic
   )
   {
      if(!Matches(ticket, symbol, magic))
         return 0.0;

      return PositionGetDouble(POSITION_VOLUME);
   }

   // Floating profit including swap.
   double FloatingProfit(
      ulong ticket,
      string symbol,
      long magic
   )
   {
      if(!Matches(ticket, symbol, magic))
         return 0.0;

      return
         PositionGetDouble(POSITION_PROFIT) +
         PositionGetDouble(POSITION_SWAP);
   }

   // Read direction.
   ENUM_POSITION_TYPE Direction(
      ulong ticket,
      string symbol,
      long magic
   )
   {
      if(!Matches(ticket, symbol, magic))
         return (ENUM_POSITION_TYPE)-1;

      return (ENUM_POSITION_TYPE)
         PositionGetInteger(POSITION_TYPE);
   }

   // Read entry price.
   double OpenPrice(
      ulong ticket,
      string symbol,
      long magic
   )
   {
      if(!Matches(ticket, symbol, magic))
         return 0.0;

      return PositionGetDouble(POSITION_PRICE_OPEN);
   }

   // Read stop-loss.
   double StopLoss(
      ulong ticket,
      string symbol,
      long magic
   )
   {
      if(!Matches(ticket, symbol, magic))
         return 0.0;

      return PositionGetDouble(POSITION_SL);
   }

   // Read take-profit.
   double TakeProfit(
      ulong ticket,
      string symbol,
      long magic
   )
   {
      if(!Matches(ticket, symbol, magic))
         return 0.0;

      return PositionGetDouble(POSITION_TP);
   }

   // Capture a complete broker-confirmed snapshot.
   bool ReadSnapshot(
      ulong ticket,
      string symbol,
      long magic,
      SManagedPositionSnapshot &snapshot
   )
   {
      ResetSnapshot(snapshot);

      if(!Matches(ticket, symbol, magic))
         return false;

      snapshot.ticket = ticket;

      snapshot.identifier =
         (ulong)PositionGetInteger(
            POSITION_IDENTIFIER
         );

      snapshot.symbol =
         PositionGetString(POSITION_SYMBOL);

      snapshot.comment =
         PositionGetString(POSITION_COMMENT);

      snapshot.magic =
         PositionGetInteger(POSITION_MAGIC);

      snapshot.openTime =
         PositionGetInteger(POSITION_TIME);

      snapshot.direction =
         (ENUM_POSITION_TYPE)
         PositionGetInteger(POSITION_TYPE);

      snapshot.openPrice =
         PositionGetDouble(POSITION_PRICE_OPEN);

      snapshot.stopLoss =
         PositionGetDouble(POSITION_SL);

      snapshot.takeProfit =
         PositionGetDouble(POSITION_TP);

      snapshot.currentVolume =
         PositionGetDouble(POSITION_VOLUME);

      snapshot.swap =
         PositionGetDouble(POSITION_SWAP);

      snapshot.floatingProfit =
         PositionGetDouble(POSITION_PROFIT) +
         snapshot.swap;

      MqlTick tick;

      if(!SymbolInfoTick(symbol, tick))
         return false;

      if(snapshot.direction == POSITION_TYPE_BUY)
         snapshot.currentPrice = tick.bid;
      else if(snapshot.direction == POSITION_TYPE_SELL)
         snapshot.currentPrice = tick.ask;
      else
         return false;

      if(
         snapshot.identifier == 0 ||
         snapshot.openPrice <= 0.0 ||
         snapshot.currentVolume <= 0.0 ||
         snapshot.currentPrice <= 0.0
      )
      {
         return false;
      }

      snapshot.valid = true;

      return true;
   }
};

#endif
