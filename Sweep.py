import re

class StopSweep(Exception):
    pass

class Sweep(list):
    DEFAULT_VALUE = 0
    def __init__(self, *args, **kwargs):
        self.is_stopped = False
        super().__init__(*args, **kwargs)
    def __iter__(self):
        i = 0
        self.is_stopped = False
        while len(self) > 0 and not self.is_stopped:
            yield self[i]
            i = (i+1)%len(self)
    def __getitem__(self, idx:int):
        res = super().__getitem__(idx%len(self))
        if isinstance(res, StopSweep):
            self.is_stopped = True
            res = self.DEFAULT_VALUE
        else:
            self.is_stopped = False
        return res
    @classmethod
    def triangle(cls, amp, off, step):
        raise NotImplementedError()
        return Sweep([])
    @classmethod
    def from_string(cls, s:str, output_type=float):
        res = []
        for x in re.split(r'[,\s;]+', s):
            if x == '':
                continue
            try:
                res.append(output_type(x))
            except:
                res.append(StopSweep())
        return Sweep(res)

if __name__ == '__main__':
    s = Sweep.from_string('1,2,3,')
    for i,x in enumerate(s):
        if i > 5:
            break
        print(i, x)
    y = iter(s)
    print('Next', next(y), next(y), next(y), next(y))

    # Output:
    # 0 1
    # 1 2
    # 2 3
    # 3 1
    # 4 2
    # 5 3
