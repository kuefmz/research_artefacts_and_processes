The NOn-STationary RAndom field model (NoStRa).

The R package NoStRa allows one to carry out numerical experiments with the 
Doubly Stochastic Advection-Diffusion-Decay Model.

The model is described in the paper
"A doubly stochastic advection-diffusion-decay model for testing  data assimilation methodologies"
by Michael Tsyrulnikov and Alexander Rakitko
(to be submited to Quart. J. Roy. Meteorol. Soc.)

With this R package, one can reproduce all the results reported in the paper.

The paper proposes a new doubly stochastic advection-diffusion-decay model defined on the 1D
spatial domain (the circle).
It is intended to be used in testing and developing data assimilation methodologies
as well as in a broader context of non-stationary spatio-temporal random field modeling.
The model is hierarchical: it is a stochastic (forced by the white noise) partial differential equation whose coefficients are spatio-temporal random fields by themselves satisfying their own stochastic partial differential equations with constant coefficients. The solution to the model is a random field that has complex spatio-temporal covariances with the tunable degree of non-stationarity. Another important feature of the model is that it allows the estimation of ``true'' space and time specific spatio-temporal covariances: both signal covariances and error covariances for any filter in question. This provides the researcher not only with the true state, as in the Observing Systems Simulation Experiments (OSSE) methodology, but also with the true error ``covariances of the day''. The capabilities of the doubly stochastic model are illustrated in numerical experiments with the Ensemble Kalman Filter (EnKF). It is shown that the accuracy of the forecast-ensemble sample covariance matrix can be substantially improved by its temporal smoothing.

The main author of the R package is Alexander Rakitko rakitko@gmail.com.

The corresponding author of the paper is Michael Tsyrulnikov mik.tsyrulnikov@gmail.com.


Manual

1. In folder Generator:

a) edit config.txt
b) execute  generate_fields.R

The output will be:

If in config.txt,
compute_field_true_covs=1,
then the output file model.RData will be created in 
Generator/Out.

If in config.txt,
perform_enkf=1, 
then the  output file filter.RData will be created in 
Generator/Out.

If in config.txt,
compute_field_true_covs=-1  and  perform_enkf=-1, 
then the  output file fields_long.RData will be created in 
Generator/Out.
This option is intended to be used with M=1 to generate
a realization of the field xi for a long time (e.g. 60000 time steps).


2. Move the file Generator/Out/fields_long.RData to folder 
Statistics/Fields_long.
Then, in folder Statistics/Fields_long, 
execute the script Exam_fields_long.R.
-> Plots with time asnd space xi correlation functions will be created.
   kurtosis(xi) will be evaluated and written to the file out_xi_all.txt.


3. Move the file Generator/Out/model.RData to folder 
Statistics/NstatioFieldCovs.
Then, in folder Statistics/NstatioFieldCovs, 
execute the script ExamDSMoutput.R.
-> Plots with the secondary fields and xi will be created 
   as well as plots with randomly chosen spatial field correlations.

4. Move the file Generator/Out/filter.RData to folder 
Statistics/Statistics/EnKF-covs.
Then, in folder EnKF-covs, execute the script ExamEnKFcovs.R.
-> Various plots related to the EnKF's prior covariances will be created.


24 Aug 2017
M.Tsyrulnikov
A.Rakitko





