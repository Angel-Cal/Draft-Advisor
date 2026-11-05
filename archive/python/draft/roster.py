class Roster:
    def __init__(self, wr_ct =3, rb_ct=2, te_ct=1, qb_ct=1, flex_ct=1, bench_size=8):
        self.wr_ct = wr_ct
        self.rb_ct = rb_ct
        self.te_ct = te_ct
        self.qb_ct = qb_ct
        self.flex_ct = flex_ct
        self.bench_size = bench_size
        self.roster_size = sum([wr_ct, rb_ct, te_ct, qb_ct, flex_ct, bench_size])
        self.qb_list= []
        self.rb_list=[]
        self.wr_list=[]
        self.te_list=[]
        self.pick_list=[]
        self.flex_filled = False
        
    
    def add_player(self, player_id, pos):
        POS_MAP= {"QB" : self.qb_list,
                  "RB" : self.rb_list,
                  "WR" : self.wr_list,
                  "TE" : self.te_list}
        POS_MAP[pos].append(player_id)
        self.pick_list.append(player_id)
        if((len(self.rb_list) >= self.rb_ct) 
                and (len(self.wr_list) >= self.wr_ct)
                and (len(self.te_list) >= self.te_ct)):
            self.flex_filled = True
    
    def get_needs(self):
        needs_list=[]
        if len(self.qb_list) < self.qb_ct:
            needs_list.append("QB")
        if len(self.rb_list) < self.rb_ct:
            needs_list.append("RB")
        if len(self.wr_list) < self.wr_ct:
            needs_list.append("WR")
        if len(self.te_list) < self.te_ct:
            needs_list.append("TE")
        if ((len(self.rb_list) >= self.rb_ct) 
                or (len(self.wr_list) >= self.wr_ct) 
                or (len(self.te_list) >= self.te_ct)) and not self.flex_filled:
            needs_list.append("FLEX")
        
        if(self.flex_filled):
            bench_used = len(self.pick_list) - self.wr_ct - self.qb_ct - self.te_ct - self.rb_ct - self.flex_ct
        else:
            bench_used = 0
        bench_remaining = self.bench_size - bench_used
        return needs_list, bench_remaining

    def get_picks(self):
        return self.pick_list