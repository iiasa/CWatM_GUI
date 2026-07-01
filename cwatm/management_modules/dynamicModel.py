# Name: Dynamic Model
# Purpose: Base framework for time-dependent model execution and temporal control.
# Provides ModelFrame class managing simulation time-stepping and state transitions.
# Supports flexible temporal resolutions and modular hydrological component integration.
# Initial and dynamic model-> idea taken from PC_Raster

class DynamicModel:
    """
    Base class for dynamic hydrological model components.
    
    Provides the foundation for time-dependent model components in CWatM.
    This class serves as a template for hydrological modules that require
    dynamic time-stepping behavior and state evolution over the simulation
    period.
    
    Attributes
    ----------
    i : int
        Simple counter attribute for model indexing.
    
    Notes
    -----
    This is a minimal base class inspired by PCRaster's dynamic modeling
    framework. Concrete hydrological modules inherit from this class and
    implement specific dynamic behaviors for water cycle processes.
    
    The class provides the structural foundation for CWatM's modular
    architecture, where individual hydrological processes are implemented
    as separate dynamic components that interact through the main model
    framework.
    """
    i = 1

# ----------------------------------------

class ModelFrame:
    """
    Execution framework for dynamic hydrological model time stepping.
    
    This class manages the temporal execution of CWatM, controlling the
    time-stepping loop and orchestrating the dynamic components of the
    hydrological model. It provides the main execution framework that
    advances the model through time, managing state transitions and
    coordinating hydrological processes.
    
    Attributes
    ----------
    _model : object
        Reference to the main CWatM model instance containing all
        hydrological components and state variables.
    currentStep : int
        Current time step number during model execution.
    
    Notes
    -----
    The ModelFrame implements the core time-stepping algorithm:
    1. Initialize model state and time counters
    2. Execute dynamic processes for each time step
    3. Update state variables and advance time
    4. Continue until simulation end
    
    This design separates the temporal execution logic from the
    hydrological process implementations, enabling modular development
    and testing of individual model components.
    
    The framework supports flexible time stepping configurations and
    can accommodate various temporal resolutions from sub-daily to
    multi-year simulations.
    """

    def __init__(self, model, lastTimeStep=1, firstTimestep=1):
        """
        Initialize the model execution framework with temporal bounds.
        
        Sets up the time-stepping framework by defining the simulation period
        and linking to the main hydrological model. Establishes the temporal
        bounds for model execution and prepares the framework for dynamic
        time stepping.
        
        Parameters
        ----------
        model : object
            Main CWatM model instance containing hydrological components,
            state variables, and process implementations.
        lastTimeStep : int, optional
            Final time step number for simulation termination. Default is 1.
        firstTimestep : int, optional
            Starting time step number for simulation initialization.
            Default is 1.
        
        Returns
        -------
        None
            Initializes the framework with temporal configuration.
        
        Notes
        -----
        The time step numbers correspond to the model's internal time
        indexing system, which is typically based on daily time steps
        but can be configured for different temporal resolutions.
        
        The model reference enables the framework to access all
        hydrological components and coordinate their execution during
        the dynamic time-stepping process.
        """

        self._model = model
        self._model.lastStep = lastTimeStep
        self._model.firstStep = firstTimestep

    def step(self):
        """
        Execute a single time step of the hydrological model.
        
        Performs one iteration of the model's dynamic processes, including
        all hydrological computations, state updates, and process interactions
        for the current time step. This is the core execution unit that
        advances the model state forward in time.
        
        Returns
        -------
        None
            Updates model state and advances time step counter.
        
        Notes
        -----
        The time step execution sequence:
        1. Set current time step in the model instance
        2. Execute all dynamic hydrological processes
        3. Update state variables and fluxes
        4. Advance to next time step
        
        This method coordinates the execution of all active hydrological
        modules including evapotranspiration, soil processes, groundwater,
        routing, and water management components.
        """
        self._model.currentStep = self.currentStep
        self._model.dynamic()
        self.currentStep += 1

    def initialize_run(self):
        """
        Initialize the model run by setting the starting time step.
        
        Prepares the time-stepping framework for dynamic execution by
        setting the current time step to the configured starting point.
        This initialization occurs before the main time-stepping loop
        begins.
        
        Returns
        -------
        None
            Sets currentStep to the model's first time step.
        
        Notes
        -----
        This method is called once at the beginning of each model run
        to establish the temporal starting point. The subsequent dynamic
        execution will iterate from this starting point to the final
        time step.
        
        The initialization is separate from the constructor to allow
        for multiple runs with the same ModelFrame instance.
        """
        # inside cwatm_dynamic it will interate
        self.currentStep = self._model.firstStep

    def run(self):
        """
        Execute the complete dynamic simulation from start to finish.
        
        Runs the full hydrological simulation by executing the time-stepping
        loop from the first to the last configured time step. This is the
        main entry point for model execution, coordinating initialization
        and the complete temporal sequence of hydrological processes.
        
        Returns
        -------
        None
            Completes the full simulation run.
        
        Notes
        -----
        The run sequence:
        1. Initialize the run with starting conditions
        2. Execute time steps sequentially until simulation end
        3. Each time step includes all active hydrological processes
        4. State variables are updated and outputs generated as configured
        
        This method orchestrates the complete CWatM simulation, managing
        the temporal progression of all hydrological components including:
        - Meteorological forcing data reading
        - Evapotranspiration calculations
        - Soil water dynamics
        - Groundwater processes
        - Surface water routing
        - Water demand and allocation
        - Output generation and reporting
        """
        self.initialize_run()
        while self.currentStep <= self._model.lastStep:
            self.step()
