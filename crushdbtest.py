
import crushdb  #This is where the DB functionality is connect,insert,update,etc
import sys
import random

sample=random.randint(1,50)
visit='1'
print(f"Test case: sample={sample} visit={visit}")

try :
    repo=crushdb.repository()
    print("Looking for preexisting data")
    measurementCount = repo.countvals(sample,visit) 
    if measurementCount>0:           
        print(f"{measurementCount} values already stored.  Some may be updated but these values are random, so who knows")
    else:
        print("...none found")
    methods=['roi','roi_end']
    measures=['a','b','c','d','e','f','g','h']

    n=500000
    print(f"Upserting {n} rows of fake data")

    for i in range(1,n):    
        roistart=random.randint(1,5000)  
        roiend=random.randint(1,5000)  
        val=random.random()
        method=methods[random.randint(0,1)]
        measure=measures[random.randint(0,7)]
        
        repo.upsert(sample,visit,roistart,roiend,method,measure,val)
    print(f"{n} rows upserted")
except Exception as e:
    print(e)



