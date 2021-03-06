#!/usr/bin/env python3

import os,sys
import psycopg2 as pg
import logging
from decimal import Decimal
from functools import wraps
from psycopg2.pool import ThreadedConnectionPool
import math
from contextlib import contextmanager
import time
import traceback

# Keep a text file to capture any errors.  
# I'm particularly interested in pooled connection failures 
# if there are too many concurrent connections.

logging.basicConfig(level=logging.ERROR, 
    format='%(asctime)s %(message)s',
    filename='crushdb-repository.log')

class repository:
    
    def __init__(self):  
        # Establish a connection pool
        # Opening connections every time is expensive, lets open a few of them, 
        # and reuse them as neeed
        # The connections in the pool will be closed then the repository memory 
        # instance is destroyed
                   
        # default is to open a connection pool of at least 2 connections. 
        # see below minconn and maxconn 
        # Adjustments may be needed.

        self.pool = self.connect() 
                              
        logging.info('Repository Instantiated')

        #if the schema doesn't exist, create it using module code schema.sql       
        schema=os.path.join(os.path.dirname(__file__), 'schema.sql')    

        # want as little possible in next 3 lines,  between getconn and putconn              
        conn = self.pool.getconn()         
        self.createdb(conn,schema)          
        self.pool.putconn(conn)   
        # quick release of connection for anyone else waiting for a connection
        # from the pool 

    def __del__(self): 
        #Indicator in logs for when teardown happens, conns close      
        logging.info('Repository Uninstantiated') 
        print("Repository Uninstantiated")



    def connect(self,env="CRUSH_DATABASE_URL", connections=2):
        """
        Connect to the database using an environment variable CRUSH_DATABASE_URL.
        """
        
        url = os.getenv(env)
        if not url:
            msg = '''no database url specified.  CRUSH_DATABASE_URL environment 
            variable must be set using example:
            postgresql://user@localhost:5432/dbname'''
            logging.error(msg)
            raise ValueError(msg)
        
        # Keep an open pool of 2 connections, but grow up to 4 as needed
        # The ThreadedConnectionPool will decide when to do garbage collection
        minconns = connections
        maxconns = connections * 2
        timeoutattempts = 100
        
        while timeoutattempts>0:
            try:
                tc = ThreadedConnectionPool(minconns, maxconns, url)  
                print("Connection Pool Established")                  
                return tc
            except:
                time.sleep(1)
                sys.stderr.write("db!")
                timeoutattempts = timeoutattempts -1 
                if timeoutattempts ==1:
                    sys.stderr.write("Stack Trace:")
                    traceback.print_exc()    
                    sys.stderr.write(f"** Attempted for 100 seconds to establish connection pool to {url}\n")                                  
                    raise RuntimeError("Unable to establish a connection pool!")
                    
        print(f"Delayed creation connection of connection pool to db {url}. {timeoutattempts} timeout seconds remaining")

    def createdb(self,conn, schema="schema.sql"):
        """
        Execute CREATE TABLE statements in the schema.sql file.
        """

        with conn.cursor() as curs:            
            sql=(
                    """select exists(SELECT FROM pg_tables WHERE tablename  = 'test_measurements')
                    """
             )               
                        
            curs.execute(sql)   
            row = curs.fetchone()       
            exists = row[0]                    
        
        exists = bool(exists) 

        if not exists:
            print(schema)        
            with open(schema, 'r') as f:
                sql = f.read()

            try:
                with conn.cursor() as curs:
                    curs.execute(sql)
                    conn.commit()
                    logging.info('Repository Instantiated')
            except Exception as e:
                conn.rollback()
                logging.error(f'Failed to create schema, ERROR:{e}')
                raise e
        
    # This will be a decorator function used below for "upsert" and "get"
    # functions.
    def transact(func):
        """
        Creates a connection per-transaction, committing when complete or
        rolling back if there is an exception. It also ensures that the conn is
        closed when we're done.
        """

        @wraps(func)
        def inner(self,*args, **kwargs):            
            with self.transaction(name=func.__name__) as conn:                    
                ret=func(self,conn, *args, **kwargs)
                return ret    
        return inner
        
    @contextmanager
    def transaction(self,name="transaction", **kwargs):
        # This is the secret ingredient, allowing us to allocate and release 
        # resources (db connections) precisely when we want to.  This minimizes
        # the time we have the connection in use

        # Get the session parameters from the kwargs
        options = {
            "isolation_level": kwargs.get("isolation_level", None),
            "readonly": kwargs.get("readonly", None),
            "deferrable": kwargs.get("deferrable", None),
        }
        
        try:
            conn = self.pool.getconn()
            conn.set_session(**options)
            yield conn
            conn.commit()
        except Exception as e:
            print(e)
            logging.info(f'Transaction failed ERROR:{e}')
            conn.rollback()           
        finally:
            conn.reset()
            self.pool.putconn(conn)
            
            
    def update_measurement(self,conn,sample,visit,roi_start,roi_end,method,measurement,measured):
        """
        Create or insert the measured value in measurements table
        """        
        #print(f"sample:{sample}, roi_start:{roi_start}, roi_end:{roi_end}, measurement:{measurement}, measured:{measured}")  

        measured = Decimal(measured)
        if(not math.isnan(measured)):
            sql=""
            try:
                with conn.cursor() as curs:
                    sql="""INSERT INTO test_measurements (sample,visit,roi_start,roi_end,method,measurement,measured)
                        VALUES('%s','%s','%s','%s','%s','%s','%36.20f') 
                        ON CONFLICT (sample,visit,roi_start,roi_end,method,measurement) 
                        DO 
                            UPDATE SET measured = EXCLUDED.measured""" %(sample,visit,roi_start,roi_end,method,measurement,measured)                                                          
                    #print(sql)
                    curs.execute(sql)
            except Exception as e:
                logging.error(f"ERROR:{e} SQL:{sql}\n")
                raise e
            
    def get_measurement(self,conn,sample,visit,roi_start,roi_end,method,measurement):
        """
        fetch the measured value in measurements table
        """                
        with conn.cursor() as curs:
            sql=(
                    """select measured from test_measurements where sample=%s and visit=%s and roi_start=%s and roi_end=%s
                    and method=%s and measurement=%s
                    """
             )               
            curs.execute(sql,(sample,visit,roi_start,roi_end,method,measurement))   
            row = curs.fetchone()             
            measured = row[0]                    
        
        measured = Float(measured)        
        return measured

    def get_measurement_count(self,conn,sample,visit):
        """
        fetch the number of measurements in measurements table for sample,visit
        """
        
        #cursor.callproc('Function_or_procedure_name',[IN and OUT parameters,])
        
        with conn.cursor() as curs:            
            sql=(
                    """select count(1) from test_measurements where sample=%s and visit=%s
                    """
             )               
                        
            curs.execute(sql,(sample,visit))   
            row = curs.fetchone()       
            measured = row[0]                    
        
        measured = int(measured)        
        return measured

    def get_all_measurements(self,conn,sample,visit):
        """
        fetch the measured values from measurements table for sample,visit
        return dictionary of name-value pairs
        """               
        Measurements={}
        with conn.cursor() as curs:
            sql=(
                    """select roi_start,roi_end,method,measurement,measured from test_measurements where sample=%s and visit=%s
                    """
             )               
            curs.execute(sql,(sample,visit))   
            row = curs.fetchone()  
            while row:
                #measured = row[0]    
                #n = levman/0251-3001-roi-VoxelSizeX=0
                n = f"{row[0]}-{row[1]}-{row[2]}-{row[3]}"
                v = row[4]                              
                Measurements[n]=v                 
                row = curs.fetchone()

        return Measurements
    def get_local_measurements(self,conn,sample,visit,roi_start,roi_end,method):
        """
        fetch the measured values from measurements table for sample,visit
        and localized region of interest
        return dictionary of name-value pairs
        """              
        Measurements={}
        with conn.cursor() as curs:
            sql=(
                    """select roi_start,roi_end,method,measurement,measured 
                    from measurements where sample=%s and visit=%s
                    and roi_start=%s and roi_end=%s and method=%s
                    """
             )               
            curs.execute(sql,(sample,visit,roi_start,roi_end,method))   
            row = curs.fetchone()    
            while row:
               
                n = f"{row[0]}-{row[1]}-{row[2]}-{row[3]}"
                v = row[4]                              
                Measurements[n]=v 
                row = curs.fetchone()    
                
        return Measurements

    @transact
    def upsert(self,conn,sample,visit, roi_start,roi_end,method,measurement,measured):               
        self.update_measurement(conn,sample,visit,roi_start,roi_end,method,measurement,measured)

    @transact
    def get(self,conn,sample,visit, roi_start,roi_end,method,measurement):        
        x=self.get_measurement(conn,sample,visit,roi_start,roi_end,method,measurement)                
        return x

    @transact
    def getall(self,conn,sample,visit):        
        x=self.get_all_measurements(conn,sample,visit)                
        return x

    @transact
    def getlocal(self,conn,sample,visit,roi_start,roi_end,method):        
        x=self.get_local_measurements(conn,sample,visit,roi_start,roi_end,method)                
        return x

    @transact
    def countvals(self,conn,sample,visit):
        x=self.get_measurement_count(conn,sample,visit)
        return x
    


