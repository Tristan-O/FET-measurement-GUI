import re

class Sweep(list):
    def __iter__(self):
        i = 0
        while len(self) > 0:
            yield self[i]
            i = (i+1)%len(self)
    @classmethod
    def triangle(cls, amp, off, step):
        raise NotImplementedError()
        return Sweep([])
    @classmethod
    def from_string(cls, s:str, output_type=float):
        return Sweep([output_type(x) for x in re.split(r'[,\\s;]+', s) if x != ''])

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
