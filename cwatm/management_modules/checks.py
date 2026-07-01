# -------------------------------------------------------------------------
# Name: Checks
# Purpose: Validate CWatM input data and provide diagnostic information
#
# Author:      burekpe
# Created:     16/05/2016
# CWatM is licensed under GNU GENERAL PUBLIC LICENSE Version 3.
# -------------------------------------------------------------------------

"""
Input validation and data quality control for CWatM.

This module provides comprehensive validation and diagnostic functions for
CWatM input data, including spatial data checking, file verification, and
detailed reporting of data characteristics. The validation system helps
ensure data quality and compatibility before model execution.

Key Functions
-------------
decompress : Convert 1D compressed arrays to 2D display format
counted : Decorator for counting function calls
checkmap : Comprehensive validation and reporting for spatial data
save_check : Save validation results to CSV files
load_global_attribute : Extract NetCDF global attributes

The module supports comparison against reference datasets and provides
detailed statistics about spatial data including:
- Spatial dimensions and valid cell counts
- Value ranges, means, and distributions  
- Missing value patterns and data completeness
- File modification dates and version tracking
"""

from .globals import *
from netCDF4 import Dataset

def decompress(map):
    """
    Decompress 1D array without missing values to 2D array with missing values.
    
    This function converts compressed 1D arrays used internally by CWatM back
    to full 2D spatial arrays for display, analysis, and output. The function
    properly handles different data types and missing value conventions.
    
    Parameters
    ----------
    map : numpy.ndarray
        1D compressed array containing only valid (non-masked) values
        
    Returns
    -------
    numpy.ndarray
        2D spatial array with proper dimensions and missing value handling
        
    Notes
    -----
    The function uses global maskinfo to determine:
    - Original spatial dimensions (maskinfo['shape'])
    - Location of valid cells (maskinfo['maskflat'])
    - Base mask array structure (maskinfo['maskall'])
    
    Missing values are set according to data type:
    - Integer types (int16, int32): -9999
    - int8 types: Negative values set to 0
    - All other types: -9999
    
    This function is essential for converting CWatM's internal compressed
    storage format back to standard spatial raster format.
    """

    dmap = maskinfo['maskall'].copy()
    dmap[~maskinfo['maskflat']] = map[:]
    dmap = dmap.reshape(maskinfo['shape'])

    # check if integer map (like outlets, lakes etc
    try:
        checkint = str(map.dtype)
    except:
        checkint = "x"
    if checkint == "int16" or checkint == "int32":
        dmap[dmap.mask] = -9999
    elif checkint == "int8":
        dmap[dmap < 0] = 0
    else:
        dmap[dmap.mask] = -9999

    return dmap

def counted(fn):
    """
    Decorator to count the number of times a function is called.
    
    This decorator adds a call counter to any function, which is useful
    for tracking how many times validation functions are executed during
    model initialization and for generating sequential output.
    
    Parameters
    ----------
    fn : callable
        Function to be wrapped with call counting functionality
        
    Returns
    -------
    callable
        Wrapped function with added 'called' attribute for call count
        
    Notes
    -----
    The wrapper function maintains the original function name and adds
    a 'called' attribute that increments each time the function is invoked.
    This is particularly useful for the checkmap function to provide
    sequential numbering in validation output.
    
    The call counter starts at 0 and increments before each function call.
    """
    def wrapper(*args, **kwargs):
        wrapper.called += 1
        return fn(*args, **kwargs)
    wrapper.called = 0
    wrapper.__name__ = fn.__name__
    return wrapper


@counted
def checkmap(name, value, map):
    """
    Comprehensive validation and diagnostic reporting for CWatM input data.
    
    This function performs detailed validation of spatial and scalar input data,
    comparing against mask requirements and providing comprehensive statistics.
    It supports reference dataset comparison and generates detailed reports.
    
    Parameters
    ----------
    name : str
        Name of the variable as specified in settings file
    value : str  
        Filename or path of the input data
    map : numpy.ndarray or scalar
        Input data - either spatial array or scalar value
        
    Notes
    -----
    The function provides comprehensive diagnostics including:
    - Spatial dimensions and cell counts
    - Data validity against mask requirements
    - Statistical summaries (min, mean, max)
    - Zero and non-zero value counts
    - File creation dates and version comparison
    - Reference dataset validation when available
    
    For spatial data, the function:
    - Decompresses 1D arrays to 2D for analysis
    - Validates coverage against the model mask
    - Handles extreme values and missing data
    - Compares valid cell counts with mask requirements
    
    Output is formatted as CSV-compatible text with headers generated
    on first call. Results are stored globally for batch reporting.
    
    The function integrates with CWatM's version control system to
    compare input data against reference datasets when available.
    """

    def load_global_attribute(filename, attribute_name):
        if not os.path.exists(filename):
            return None

        try:
            with Dataset(filename, 'r') as nc_file:
                if attribute_name in nc_file.ncattrs():
                    return str(nc_file.getncattr(attribute_name))
                else:
                    return None
        except Exception:
            return None

    def input2str(inp):
        if isinstance(inp, str):
            return(inp)
        elif isinstance(inp, int):
            return f'{inp}'
        else:
            if inp < 100000:
                return f'{inp:.2f}'
            else:
                return f'{inp:.2E}'
        
    # ------------------------
    # if args[] is a netcdf then load this and analyse
    args = versioning['checkargs']
    if versioning['loadinput'] and len(args)>1:
        if args[1][-3:] == ".nc":
            # load discharge netcdf but only attribute version_inputfiles
            ver_input = load_global_attribute(args[1],"version_inputfiles")
            versioning['loadinput'] = False
            versioning['refvalue'] = True

            # put information on input data into dictorary
            versioning['checkinput'] = {}
            pairs = ver_input.split(';')
            for pair in pairs:
                if not pair.strip():
                    continue
                parts = pair.split(' ', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    date1 = parts[1].strip()
                else:
                    date1 = ""
                versioning['checkinput'][key] = date1





    # ----------------------------------
    # stored inputdate with date (addtoversiondate in data_handling.py)
    # (name, value, map):

    inputver =versioning['input'].split(";")
    # dictorary with each file and date
    inputv = {}
    for v in inputver[0:-1]:
        vv = v.split(" ")
        inputv[vv[0]] = vv[1] + " "+ vv[2]


    s = [name]
    #s.append(os.path.dirname(value))
    iv = os.path.basename(value)
    s.append(iv)
    # check for filename and get date
    createdate = inputv.get(iv, " ")
    s.append(createdate)

    # if a reference inputfile is used
    if versioning['refvalue']:
        refdate = versioning['checkinput'].get(iv, "")
        s.append(refdate)
        if refdate != "":
            if refdate == createdate:
                s.append("True")
            else:
                s.append("False")
        else:
            s.append(" ")

    # evaluate maps
    # if it is notr a number but a map (.tif, .nc, .map)
    flagmap = False
    if isinstance(map, np.ndarray):
        flagmap = True
        mapshape = map.shape
        # ifr compressed -> decompress
        if len(mapshape) < 2:
            map = decompress(map)
            mapshape = map.shape

    if flagmap:
        # if smaller than 0 or bigger than 1e20 => nan
        map = np.where(map<-100, np.nan, map)
        map = np.where(map > 1e20, np.nan, map)
        mapshape = input2str(map.shape[0]) + "x" + input2str(map.shape[1])

        #maskinfo['mask']
        # check if there are less valid cells than there should be compared to maskmap
        # reverse maskmap -> every valid cell has a True
        mask = ~maskinfo['mask']
        # count number of must cells
        numbermask = np.nansum(mask)
        vmap = ~np.isnan(map)
        andmap = mask & vmap
        # count number of cell in map
        numbermap = np.nansum(andmap)

        # if this is less the the must cell -> problem
        valid = "True"
        if numbermap < numbermask:
            valid = "False"


        numbernonzero = np.count_nonzero(map)
        numberzero = map.shape[0] * map.shape[1] - np.count_nonzero(map)

        minmap = map[~np.isnan(map)].min()
        meanmap = map[~np.isnan(map)].mean()
        maxmap = map[~np.isnan(map)].max()

        s.append(mapshape)
        s.append(input2str(int(numbermap)))
        s.append(valid)
        s.append(input2str(numberzero))
        s.append(input2str(numbernonzero))
        s.append("    ")
        s.append(input2str(minmap))
        s.append(input2str(meanmap))
        s.append(input2str(maxmap))
        s.append(os.path.dirname(value))

    # if it is a number
    else:
        #s.append(input2str(float(map)))
        for i in range(10):
            s.append("")




    # if it is checked against a discharge...nc
    if versioning['refvalue']:
        t = ["<30", "<80", "<20","<20","<10",">11", ">11", ">11", ">11", ">11", ">11", ">11", ">11", ">11", ">11", ">11", "<80"]
        h = ["Name", "File/Value", "Create Date","Ref Date","Same Date", "x-y", "number valid", "valid", "Zero values", "NonZero","-----",
             "min", "mean", "max", "Path"]
    # or without comparsion
    else:
        t = ["<30","<80","<20"   ,">11",">11",">11",">11",">11",">11",">11",">11",">11", ">11",">11","<80"]
        h = ["Name","File/Value","Create Date", "x-y", "number valid", "valid", "Zero values", "NonZero","-----",
             "min", "mean", "max", "Path"]

    # if checkmap is called for the first time
    if checkmap.called == 1:
        """
        s1= "----\n"
        s1 += "nonMV,non missing value in 2D map\n"
        s1 += "MV,missing value in 2D map\n"
        s1 += "lon-lat,longitude x latitude of 2D map\n"
        s1 += "CompressV,2D is compressed to 1D?\n"
        s1 += "MV-comp,missing value in 1D\n"
        s1 += "Zero-comp,Number of 0 in 1D\n"
        s1 += "NonZero,Number of non 0 in 1D\n"
        s1 += "min,minimum in 1D (or 2D)\n"
        s1 += "mean,mean in 1D (or 2D)\n"
        s1 += "max,maximum in 1D (or 2D)\n"
        s1 += "-----\n"
        """
        s1 =""
        # put all the header (keys) in a text line
        for i in range(len(s)):
            s1 += f'{h[i]:{t[i]}}'
            if i<(len(s)-1):
                s1 += ","
            else:
                s1 += "\n"
        print(s1)
        versioning['check'] += s1

    # put all the values in a text file
    s2 = ""
    for i in range(len(s)):
        s2 += f'{s[i]:{t[i]}}'
        if i < (len(s) - 1):
            s2 += ","
        else:
            s2 += "\n"
    versioning['check'] += s2
    s2 = str(checkmap.called) + " " + s2
    print (s2)

    return

def save_check():
    """
    Save validation results to CSV file.
    
    This function writes accumulated validation results from checkmap calls
    to a CSV file for external analysis. The output location is determined
    from command-line arguments stored in the versioning system.
    
    Notes
    -----
    The function handles two argument patterns:
    1. Three arguments: settings.ini, reference.nc, output.csv
    2. Two arguments: settings.ini, output.csv
    
    File saving occurs only when:
    - Valid arguments are provided with .csv extension
    - Validation results have been accumulated in versioning['check']
    
    After saving, the checkmap call counter is reset to 0 for potential
    future validation runs. The CSV output includes headers and formatted
    data for each validated input.
    
    The saved file can be analyzed externally to:
    - Compare multiple model setups
    - Track data quality over time
    - Validate input data consistency
    - Document model configuration for reproducibility
    """

    save = False
    checkmap.called = 0
    args = versioning['checkargs']
    if len(args)>1:
        if len(args) > 2 and args[1][-3:] == ".nc":
            if args[2][-4:] == ".csv":
                save = True
                savefile = args[2]
        else:
            if args[1][-4:] == ".csv":
                save = True
                savefile = args[1]
    if save:
        with open(savefile, 'w', encoding='utf-8') as f:
            f.write(versioning['check'])
    return








